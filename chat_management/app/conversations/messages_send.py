import asyncio
import io
import json
import logging
import os
import socket
import traceback
import uuid
from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import BaseQuery

from .schemas import Message, MessageType, MessageCreate, FileInfo, FileMessageCreate
from ..aws.sqs_utils import is_sqs_available
from ..aws.s3_utils import s3_client
from ..aws.config import settings
from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user, verify_conversation_participant
from ..firebase import firestore_db
from ..notifications.service import NotificationService
from ..pagination import PaginatedResponse, PaginationParams, common_pagination_parameters
from ..redis.connection import get_redis_connection
from ..time_utils import convert_timestamps
from ..ws.router import get_connection_manager

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(decode_token)],
)

notification_service = NotificationService()
connection_manager = get_connection_manager()
tags = ["Messages"]

@router.post('/conversations/{conversation_id}/messages',
             tags=tags,
             dependencies=[Depends(verify_conversation_participant)])
async def send_conversation_message(
        conversation_id: str,
        message: MessageCreate,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Send a message to a specific conversation using the new message flow architecture

    Args:
        conversation_id: The ID of the conversation to send the message to
        message: The message creation data (content and type)
        current_user: The authenticated user making the request

    Returns:
        dict: Message ID, timestamp, and status

    Raises:
        400: If content is missing or message type is invalid
        403: If the user is not a participant in the conversation
        404: If the conversation doesn't exist
        500: If there's a database or other error
    """
    # Validate request data
    content = message.content
    message_type = message.messageType

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Content is required"
        )

    # Validate message type
    if message_type not in [m.value for m in MessageType]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid message type. Must be one of: {[m.value for m in MessageType]}"
        )

    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = await asyncio.to_thread(conversation_ref.get)
    conversation_data = conversation.to_dict()

    # Create message
    message_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    message_data = {
        'content': content,
        'messageType': message_type,
        'senderId': current_user.phoneNumber,
        'timestamp': now,
        'readBy': [current_user.phoneNumber]  # Sender has read their own message
    }

    # Step 1: Save message to Firestore
    try:
        message_ref = firestore_db.collection('conversations').document(conversation_id).collection(
            'messages').document(message_id)
        await asyncio.to_thread(message_ref.set, message_data)
        logger.info(f"Message {message_id} saved to Firestore for conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Error storing message in Firestore: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save message"
        )

    # Step 2: Update conversation metadata
    try:
        # Create a preview (truncate if longer than 50 chars)
        preview = content[:50] + ('...' if len(content) > 50 else '')
        await asyncio.to_thread(
            conversation_ref.update,
            {
                'lastMessageTime': firestore.SERVER_TIMESTAMP,
                'lastMessagePreview': preview,
                'lastMessageType': message_type,
                'lastMessageSenderId': current_user.phoneNumber
            }
        )
        logger.info(f"Conversation {conversation_id} metadata updated")
    except Exception as e:
        logger.error(f"Error updating conversation metadata: {str(e)}")
        # Continue processing even if metadata update fails

    # Step 2.5: Update unread counts for all participants except the sender
    try:
        participants = conversation_data.get('participants', [])
        sender_id = current_user.phoneNumber
        batch = firestore_db.batch()

        # Create a batch to update all participants' unread counts atomically
        for participant in participants:
            if participant == sender_id:
                continue  # Skip sender, they've already read the message

            # Get user stats reference
            user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                             .collection('user_stats').document(participant)

            # Check if user stats exist first
            user_stats = await asyncio.to_thread(user_stats_ref.get)

            if user_stats.exists:
                # Increment existing unread count
                current_count = user_stats.to_dict().get('unreadCount', 0)
                batch.update(user_stats_ref, {'unreadCount': current_count + 1})
            else:
                # Create new user stats with unread count of 1
                batch.set(user_stats_ref, {
                    'unreadCount': 1,
                    'lastReadMessageId': None
                })

        # Commit all the unread count updates
        await asyncio.to_thread(batch.commit)
        logger.info(f"Updated unread counts for participants in conversation {conversation_id}")
    except Exception as e:
        logger.error(f"Error updating unread counts: {str(e)}")
        # Continue processing even if unread count updates fail

    # Step 3: Publish to Redis Pub/Sub for real-time notifications
    try:
        # Get Redis connection
        redis_conn = await get_redis_connection()

        # Create message event data for publishing
        message_event = {
            'event': 'new_message',
            'conversationId': conversation_id,
            'messageId': message_id,
            'senderId': current_user.phoneNumber,
            'content': content,
            'messageType': message_type,
            'timestamp': now.isoformat(),
            'instanceId': os.environ.get("INSTANCE_ID", socket.gethostname()),
            'participants': conversation_data.get('participants', [])
        }

        # Publish to Redis channel for this conversation
        channel = f"conversation:{conversation_id}"
        pub_result = await redis_conn.publish(channel, json.dumps(message_event))

        if pub_result:
            logger.info(f"Message event published to Redis channel {channel} with {pub_result} receivers")
        else:
            logger.warning(f"Published to Redis channel {channel} but found no subscribers")
            # This is not an error - just means no online users are listening on the given channel
            # We'll still process offline notifications below
    except Exception as e:
        logger.error(f"Error with Redis Pub/Sub: {str(e)}")
        # Fallback to direct WebSocket broadcast if Redis is not available
        try:
            await broadcast_message(conversation_id, message_id, current_user.phoneNumber, content, message_type)
            logger.info(f"Used direct WebSocket broadcast as Redis fallback for message {message_id}")
        except Exception as ws_error:
            logger.error(f"Error broadcasting message via WebSocket fallback: {str(ws_error)}")
            # Don't fail the API request if WebSocket delivery fails - we'll still process offline notifications

    # Step 4: Send offline push notifications via SQS/Notification Consumer
    participants = conversation_data.get('participants', [])
    # Run this in a background task to not block the API response
    asyncio.create_task(
        process_offline_notifications(
            conversation_id=conversation_id,
            message_id=message_id,
            sender_id=current_user.phoneNumber,
            content=content,
            message_type=message_type,
            timestamp=now,
            participants=participants
        )
    )

    # Return success response
    return {
        'messageId': message_id,
        'timestamp': now.isoformat(),
        'status': 'sent'
    }

@router.post('/conversations/{conversation_id}/files',
             tags=tags,
             dependencies=[Depends(verify_conversation_participant)])
async def upload_conversation_file(
        conversation_id: str,
        messageType: Annotated[str, Form()],
        file: Annotated[UploadFile, File()],
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
        description: Annotated[Optional[str], Form()] = None,
):
    """
    Upload a file to a conversation and create a file message

    Args:
        conversation_id: The ID of the conversation
        messageType: The type of file message (image, video, audio, file)
        file: The file to upload
        description: Optional description of the file
        current_user: The authenticated user making the request

    Returns:
        dict: Message ID, file URL, and status

    Raises:
        400: If file or message type is invalid
        403: If the user is not a participant in the conversation
        404: If the conversation doesn't exist
        500: If there's a database, S3, or other error
    """
    # Validate message type for file uploads
    if messageType not in [MessageType.IMAGE.value, MessageType.VIDEO.value,
                         MessageType.AUDIO.value, MessageType.FILE.value]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file message type. Must be one of: {[MessageType.IMAGE.value, MessageType.VIDEO.value, MessageType.AUDIO.value, MessageType.FILE.value]}"
        )

    # Validate file exists
    if not file or not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is required"
        )

    # Validate file type if S3 client is available
    content_type = file.content_type or "application/octet-stream"
    if s3_client and not s3_client.is_file_type_allowed(content_type):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type {content_type} is not allowed"
        )

    # Read the file into memory to validate size
    file_content = await file.read()
    file_size = len(file_content)

    # Validate file size against the configured maximum
    if file_size > settings.aws_s3_max_file_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File size exceeds the maximum allowed size of {settings.aws_s3_max_file_size / (1024 * 1024):.1f} MB"
        )

    # Rewind file for later use
    file_object = io.BytesIO(file_content)

    # Check if S3 client is available
    if not s3_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File upload service is not available"
        )

    # Get conversation data
    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = await asyncio.to_thread(conversation_ref.get)
    conversation_data = conversation.to_dict()

    # Generate a unique S3 key for the file
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    unique_filename = f"{timestamp}_{uuid.uuid4()}_{file.filename}"
    # Include conversation_id in the path for better organization and security
    s3_key = f"conversations/{conversation_id}/{messageType}/{unique_filename}"

    try:
        # We already have the file content and file_object from validation above
        # The content_type is also already set

        # Upload the file to S3
        await s3_client.upload_file(
            file_obj=file_object,
            object_name=s3_key,
            content_type=content_type
        )
        logger.info(f"File uploaded to S3 with key: {s3_key}")

        # Generate a pre-signed URL for the file
        file_url = s3_client.generate_presigned_url(s3_key)

        # Create file info object
        file_info = FileInfo(
            filename=file.filename,
            size=len(file_content),
            mime_type=content_type,
            s3_key=s3_key
        )

        # Create message with file info
        message_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Use description as content if provided, otherwise use filename
        content = description if description else file.filename

        message_data = {
            'content': content,
            'messageType': messageType,
            'senderId': current_user.phoneNumber,
            'timestamp': now,
            'readBy': [current_user.phoneNumber],  # Sender has read their own message
            'file_info': {
                'filename': file.filename,
                'size': len(file_content),
                'mime_type': content_type,
                's3_key': s3_key
            }
        }

        # Save message to Firestore
        message_ref = firestore_db.collection('conversations').document(conversation_id).collection(
            'messages').document(message_id)
        await asyncio.to_thread(message_ref.set, message_data)
        logger.info(f"File message {message_id} saved to Firestore for conversation {conversation_id}")

        # Update conversation metadata
        preview = f"{messageType.capitalize()}: {file.filename}"
        await asyncio.to_thread(
            conversation_ref.update,
            {
                'lastMessageTime': firestore.SERVER_TIMESTAMP,
                'lastMessagePreview': preview,
                'lastMessageType': messageType,
                'lastMessageSenderId': current_user.phoneNumber
            }
        )

        # Update unread counts for all participants except the sender
        try:
            participants = conversation_data.get('participants', [])
            sender_id = current_user.phoneNumber
            batch = firestore_db.batch()

            # Create a batch to update all participants' unread counts atomically
            for participant in participants:
                if participant == sender_id:
                    continue  # Skip sender, they've already read the message

                # Get user stats reference
                user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                                 .collection('user_stats').document(participant)

                # Check if user stats exist first
                user_stats = await asyncio.to_thread(user_stats_ref.get)

                if user_stats.exists:
                    # Increment existing unread count
                    current_count = user_stats.to_dict().get('unreadCount', 0)
                    batch.update(user_stats_ref, {'unreadCount': current_count + 1})
                else:
                    # Create new user stats with unread count of 1
                    batch.set(user_stats_ref, {
                        'unreadCount': 1,
                        'lastReadMessageId': None
                    })

            # Commit all the unread count updates
            await asyncio.to_thread(batch.commit)
            logger.info(f"Updated unread counts for participants in conversation {conversation_id}")
        except Exception as e:
            logger.error(f"Error updating unread counts: {str(e)}")
            # Continue processing even if unread count updates fail

        # Publish to Redis for real-time notifications
        try:
            redis_conn = await get_redis_connection()

            message_event = {
                'event': 'new_message',
                'conversationId': conversation_id,
                'messageId': message_id,
                'senderId': current_user.phoneNumber,
                'content': content,
                'messageType': messageType,
                'timestamp': now.isoformat(),
                'instanceId': os.environ.get("INSTANCE_ID", socket.gethostname()),
                'participants': conversation_data.get('participants', []),
                'file_url': file_url,  # Include the file URL for clients
                'file_info': file_info.dict()  # Include file metadata
            }

            channel = f"conversation:{conversation_id}"
            pub_result = await redis_conn.publish(channel, json.dumps(message_event))

            if pub_result:
                logger.info(f"File message event published to Redis channel {channel}")
            else:
                logger.warning(f"Published to Redis channel {channel} but found no subscribers")
        except Exception as e:
            logger.error(f"Error with Redis Pub/Sub: {str(e)}")
            # Fallback to direct WebSocket broadcast
            try:
                # Add file info to the message for WebSocket broadcast
                await broadcast_file_message(conversation_id, message_id, current_user.phoneNumber,
                                       content, messageType, file_url, file_info.dict())
            except Exception as ws_error:
                logger.error(f"Error broadcasting file message via WebSocket: {str(ws_error)}")

        # Process offline notifications in background
        participants = conversation_data.get('participants', [])
        asyncio.create_task(
            process_offline_notifications(
                conversation_id=conversation_id,
                message_id=message_id,
                sender_id=current_user.phoneNumber,
                content=content,
                message_type=messageType,
                timestamp=now,
                participants=participants
            )
        )

        # Return success response with file URL
        return {
            'messageId': message_id,
            'file_url': file_url,
            'timestamp': now.isoformat(),
            'status': 'sent'
        }

    except Exception as e:
        logger.error(f"Error uploading file or creating file message: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )


async def broadcast_file_message(conversation_id: str, message_id: str, sender_id: str, 
                           content: str, message_type: str, file_url: str, file_info: dict):
    """
    Broadcast a file message to all participants in a conversation using WebSocket
    This is a fallback method used when Redis PubSub is not available
    
    Args:
        conversation_id: The ID of the conversation
        message_id: The ID of the message
        sender_id: The ID of the sender
        content: The message content
        message_type: The message type
        file_url: The presigned URL to access the file
        file_info: File metadata
    """
    # Prepare the event data
    message_event = {
        'event': 'new_message',
        'conversationId': conversation_id,
        'messageId': message_id,
        'senderId': sender_id,
        'content': content,
        'messageType': message_type,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'file_url': file_url,
        'file_info': file_info
    }

    # Use the connection manager to broadcast the message
    await connection_manager.broadcast_to_conversation(message_event, conversation_id, skip_user_id=sender_id)
    logger.debug(f"Directly broadcast file message {message_id} to conversation {conversation_id} via WebSocket")

async def broadcast_message(conversation_id: str, message_id: str, sender_id: str, content: str, message_type: str):
    """
    Broadcast a message to all participants in a conversation using WebSocket
    This is a fallback method used when Redis PubSub is not available
    
    Args:
        conversation_id: The ID of the conversation
        message_id: The ID of the message
        sender_id: The ID of the sender
        content: The message content
        message_type: The message type
    """
    # Prepare the event data
    message_event = {
        'event': 'new_message',
        'conversationId': conversation_id,
        'messageId': message_id,
        'senderId': sender_id,
        'content': content,
        'messageType': message_type,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    # Use the connection manager to broadcast the message
    await connection_manager.broadcast_to_conversation(message_event, conversation_id, skip_user_id=sender_id)
    logger.debug(f"Directly broadcast message {message_id} to conversation {conversation_id} via WebSocket")
    

async def process_offline_notifications(conversation_id: str, message_id: str, sender_id: str, 
                                        content: str, message_type: str, timestamp: datetime,
                                        participants: List[str]):
    """
    Process offline notifications for a message
    This function sends notifications to the SQS queue for handling by the notification consumer service
    
    Args:
        conversation_id: The ID of the conversation
        message_id: The ID of the message
        sender_id: The ID of the sender
        content: The message content
        message_type: The message type
        timestamp: The message timestamp
        participants: List of participant IDs
    """
    notification_sent = False
    
    try:
        # First check Redis to see which users have active connections
        try:
            redis_conn = await get_redis_connection()
            online_users = []
            
            # Check each participant to see if they have active connections
            for participant in participants:
                if participant == sender_id:
                    continue  # Skip sender, they don't need a notification
                    
                # Check if user has any active connections in Redis
                conn_count = await redis_conn.hlen(f"connections:{participant}")
                if conn_count > 0:
                    online_users.append(participant)
            
            # Remove online users from notification list
            offline_participants = [p for p in participants if p != sender_id and p not in online_users]
            
            if not offline_participants:
                logger.info(f"All participants for message {message_id} are online, no offline notifications needed")
                return
                
            logger.info(f"Found {len(offline_participants)} offline participants needing notifications")
            
            # Update participants list to only include offline users
            participants = offline_participants
        except Exception as e:
            logger.error(f"Error checking online status in Redis: {str(e)}")
            # Continue with all participants if we can't check Redis
            # We'll remove the sender at least
            participants = [p for p in participants if p != sender_id]
        
        # Prepare notification data for the queue with the standardized format
        # expected by the notification consumer service
        notification_data = {
            'event': 'new_message',
            'eventType': 'new_message',  # Explicit event type field
            'conversationId': conversation_id,
            'messageId': message_id,
            'eventId': message_id,  # Include eventId for consumer compatibility
            'senderId': sender_id,
            'content': content,
            'messageType': message_type,
            'timestamp': timestamp.isoformat(),
            'participants': participants
        }
            
        # Try SQS if available
        if is_sqs_available():
            try:
                # Send to the notification queue using the notification service
                notification_sent = await notification_service.send_message_to_queue(notification_data)

                if notification_sent:
                    logger.info(f"Notification for message {message_id} sent to SQS queue for {len(participants)} recipients")
                else:
                    logger.warning(f"Failed to send notification for message {message_id} to SQS queue")
            except Exception as e:
                logger.error(f"Error sending notification to SQS: {str(e)}")
                notification_sent = False

        # If SQS is not available or notification failed, use direct processing
        if not notification_sent:
            logger.info("Using direct notification processing as fallback")
            try:
                # Process notification directly
                await notification_service.process_new_message(notification_data)
                logger.info(f"Processed direct notifications for {len(participants)} recipients")
            except Exception as e:
                logger.error(f"Error in direct notification processing: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing offline notifications: {str(e)}")
        # Don't fail the request if notification processing fails
