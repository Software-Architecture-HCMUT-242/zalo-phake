import asyncio
import json
import logging
import os
import socket
import uuid
from datetime import datetime, timezone
from typing import Annotated, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from firebase_admin import firestore

from ..aws.sqs_utils import is_sqs_available, send_chat_message_notification
from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user
from ..firebase import firestore_db
from ..redis.connection import get_redis_connection
from .schemas import Message, MessageType, MessageCreate
from ..notifications.service import NotificationService
from ..pagination import PaginatedResponse, PaginationParams, common_pagination_parameters
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


@router.get('/{conversation_id}/messages', response_model=PaginatedResponse[Message], tags=tags)
async def get_conversation_messages(
        conversation_id: str,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
        pagination: Annotated[PaginationParams, Depends(common_pagination_parameters)]
):
    """
    Get paginated messages for a specific conversation
    
    Args:
        conversation_id: The ID of the conversation to retrieve messages from
        current_user: The authenticated user making the request
        pagination: Pagination parameters (page, size)
        
    Returns:
        PaginatedResponse: A paginated list of messages
        
    Raises:
        404: If the conversation doesn't exist
        403: If the user is not a participant in the conversation
    """
    # Verify the conversation exists
    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = await asyncio.to_thread(conversation_ref.get)

    if not conversation.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Conversation not found"
        )

    # Verify the user is a participant in the conversation
    conversation_data = conversation.to_dict()
    if current_user.phoneNumber not in conversation_data.get('participants', []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="User is not a participant in this conversation"
        )

    # Query messages for this conversation
    messages_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages')
    query = messages_ref.order_by('timestamp', direction='DESCENDING')

    # Get total count for pagination
    try:
        total_docs = await asyncio.to_thread(query.get)
        total_messages = len(total_docs)
    except Exception as e:
        logger.error(f"Error fetching message count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to retrieve messages"
        )

    # Apply pagination
    try:
        offset = (pagination.page - 1) * pagination.size
        paginated_msgs = await asyncio.to_thread(query.offset(offset).limit(pagination.size).get)
    except Exception as e:
        logger.error(f"Error applying pagination: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to retrieve messages"
        )

    # Transform messages to the response model
    messages = []
    for msg in paginated_msgs:
        try:
            msg_data = msg.to_dict()
            # Convert Firestore timestamps to datetime objects
            msg_data = convert_timestamps(msg_data)

            # Create Message object
            messages.append(Message(
                messageId=msg.id,
                senderId=msg_data.get('senderId'),
                content=msg_data.get('content', ''),
                messageType=msg_data.get('messageType', MessageType.TEXT),
                timestamp=msg_data.get('timestamp', datetime.now(timezone.utc)),
                readBy=msg_data.get('readBy', [])
            ))
        except Exception as e:
            logger.error(f"Error processing message {msg.id}: {str(e)}")
            # Continue to next message instead of failing the entire request

    # Create the paginated response
    return PaginatedResponse.create(
        items=messages,
        total=total_messages,
        page=pagination.page,
        size=pagination.size
    )


@router.post('/{conversation_id}/messages')
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

    # Verify conversation exists and user is a participant
    try:
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = await asyncio.to_thread(conversation_ref.get)

        if not conversation.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation_data = conversation.to_dict()
        if current_user.phoneNumber not in conversation_data.get('participants', []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a participant in this conversation"
            )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error validating conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to access conversation data"
        )

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
    
    # Step 4: Send offline push notifications via SQS/Lambda if needed
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


@router.post('/{conversation_id}/messages/{message_id}/read', tags=tags)
async def mark_message_as_read(
        conversation_id: str,
        message_id: str,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Mark a message as read by the current user and broadcast read receipt
    
    Args:
        conversation_id: The ID of the conversation containing the message
        message_id: The ID of the message to mark as read
        current_user: The authenticated user making the request
        
    Returns:
        dict: Success status
        
    Raises:
        403: If the user is not a participant in the conversation
        404: If the conversation or message doesn't exist
        500: If there's a database or other error
    """
    user_id = current_user.phoneNumber
    
    # Verify user is part of this conversation
    try:
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = await asyncio.to_thread(conversation_ref.get)

        if not conversation.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation_data = conversation.to_dict()
        if user_id not in conversation_data.get('participants', []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a participant in this conversation"
            )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error validating conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to access conversation data"
        )

    # Get the message and update read status using transaction
    try:
        # Get the message reference
        message_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages').document(message_id)
        
        # Use transaction to update read status
        transaction = firestore_db.transaction()
        
        @firestore.transactional
        def update_read_status(transaction, message_ref, user_id):
            message = message_ref.get(transaction=transaction)
            
            if not message.exists:
                return False, "Message not found"
                
            message_data = message.to_dict()
            read_by = message_data.get('readBy', [])
            
            # Only update if the user hasn't already read the message
            if user_id not in read_by:
                read_by.append(user_id)
                transaction.update(message_ref, {'readBy': read_by})
                return True, None
            
            # Message was already read by this user
            return False, None
        
        # Execute the transaction
        updated, error_message = update_read_status(transaction, message_ref, user_id)
        
        if error_message:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_message
            )
            
        if updated:
            logger.info(f"Message {message_id} marked as read by user {user_id}")
        else:
            logger.info(f"Message {message_id} was already read by user {user_id}")
            
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error updating read status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update read status"
        )

    # Notify other participants via Redis PubSub that message has been read
    try:
        # Get Redis connection
        redis_conn = await get_redis_connection()
        
        # Create read receipt event
        read_event = {
            'event': 'message_read',
            'conversationId': conversation_id,
            'messageId': message_id,
            'userId': user_id,
            'instanceId': os.environ.get("INSTANCE_ID", socket.gethostname())
        }
        
        # Publish to Redis channel
        channel = f"conversation:{conversation_id}"
        pub_result = await redis_conn.publish(channel, json.dumps(read_event))
        
        if pub_result:
            logger.info(f"Read receipt published to Redis channel {channel} with {pub_result} receivers")
        else:
            logger.info(f"Published read receipt to Redis channel {channel} but found no subscribers")
    except Exception as e:
        logger.error(f"Error publishing read receipt to Redis: {str(e)}")
        # Fallback to direct WebSocket broadcast if Redis is not available
        try:
            read_event = {
                'event': 'message_read',
                'conversationId': conversation_id,
                'messageId': message_id,
                'userId': user_id
            }
            await connection_manager.broadcast_to_conversation(read_event, conversation_id, skip_user_id=user_id)
            logger.info(f"Used direct WebSocket broadcast as Redis fallback for read receipt")
        except Exception as ws_error:
            logger.error(f"Error broadcasting read receipt via WebSocket: {str(ws_error)}")
            # Don't fail the request if WebSocket notification fails

    return {'status': 'success'}


# Add a REST API endpoint for typing indicators
@router.post('/{conversation_id}/typing', tags=tags)
async def send_typing_notification(
        conversation_id: str,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Send a typing notification to all participants in a conversation
    
    Args:
        conversation_id: The ID of the conversation where typing is occurring
        current_user: The authenticated user making the request
        
    Returns:
        dict: Success status
        
    Raises:
        403: If user is not a participant in the conversation
        404: If conversation doesn't exist
        500: If there's a database or other error
    """
    user_id = current_user.phoneNumber
    
    # Verify conversation exists and user is a participant
    try:
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = await asyncio.to_thread(conversation_ref.get)

        if not conversation.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation_data = conversation.to_dict()
        if user_id not in conversation_data.get('participants', []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a participant in this conversation"
            )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error validating conversation: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to access conversation data"
        )
    
    # Send typing notification via Redis PubSub
    try:
        # Get Redis connection
        redis_conn = await get_redis_connection()
        
        # Create typing event
        typing_event = {
            'event': 'typing',
            'conversationId': conversation_id,
            'userId': user_id,
            'instanceId': os.environ.get("INSTANCE_ID", socket.gethostname())
        }
        
        # Publish to Redis channel
        channel = f"conversation:{conversation_id}"
        pub_result = await redis_conn.publish(channel, json.dumps(typing_event))
        
        if pub_result:
            logger.debug(f"Typing notification published to Redis channel {channel} with {pub_result} receivers")
        else:
            logger.debug(f"Published typing notification to Redis channel {channel} but found no subscribers")
        
        return {'status': 'success'}
    except Exception as e:
        logger.error(f"Error publishing typing notification to Redis: {str(e)}")
        
        # Fallback to direct WebSocket broadcast if Redis is not available
        try:
            # Get the connection manager
            connection_manager = get_connection_manager()
            
            # Send typing notification via WebSocket
            await connection_manager.handle_typing_notification(conversation_id, user_id)
            logger.info(f"Used direct WebSocket broadcast as Redis fallback for typing notification")
            
            return {'status': 'success'}
        except Exception as ws_error:
            logger.error(f"Error sending typing notification via WebSocket: {str(ws_error)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send typing notification"
            )


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
    This function handles SQS queue sending for offline users who aren't connected via WebSocket
    
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
            
        # Try SQS if available
        if is_sqs_available():
            try:
                notification_sent = await send_chat_message_notification(
                    chat_id=conversation_id,
                    message_id=message_id,
                    sender_id=sender_id,
                    content=content,
                    message_type=message_type,
                    participants=participants
                )

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
                # Prepare message for direct notification processing
                notification_data = {
                    'event': 'new_message',
                    'conversationId': conversation_id,
                    'messageId': message_id,
                    'senderId': sender_id,
                    'content': content,
                    'messageType': message_type,
                    'timestamp': timestamp.isoformat(),
                    'participants': participants
                }

                # Process notification directly
                await notification_service.process_new_message(notification_data)
                logger.info(f"Processed direct notifications for {len(participants)} recipients")
            except Exception as e:
                logger.error(f"Error in direct notification processing: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing offline notifications: {str(e)}")
        # Don't fail the request if notification processing fails
