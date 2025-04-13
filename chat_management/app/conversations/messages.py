import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from firebase_admin import firestore

from ..aws.sqs_utils import is_sqs_available, send_chat_message_notification
from ..dependencies import token_required, AuthenticatedUser, get_current_active_user
from ..firebase import firestore_db
from .schemas import Message, MessageType
from ..notifications.service import NotificationService
from ..pagination import PaginatedResponse, PaginationParams, common_pagination_parameters
from ..time_utils import convert_timestamps
from ..ws.router import get_connection_manager

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(token_required)],
)

notification_service = NotificationService()
connection_manager = get_connection_manager()


@router.get('/{conversation_id}/messages', response_model=PaginatedResponse[Message])
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
    conversation = conversation_ref.get()

    if not conversation.exists:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Verify the user is a participant in the conversation
    conversation_data = conversation.to_dict()
    if current_user.phoneNumber not in conversation_data.get('participants', []):
        raise HTTPException(status_code=403, detail="User is not a participant in this conversation")

    # Query messages for this conversation
    messages_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages')
    query = messages_ref.order_by('timestamp', direction='DESCENDING')

    # Get total count for pagination
    try:
        total_docs = query.get()
        total_messages = len(total_docs)
    except Exception as e:
        logger.error(f"Error fetching message count: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve messages")

    # Apply pagination
    try:
        offset = (pagination.page - 1) * pagination.size
        paginated_msgs = query.offset(offset).limit(pagination.size).get()
    except Exception as e:
        logger.error(f"Error applying pagination: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve messages")

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
        request: Request,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Send a message to a specific conversation
    
    Args:
        conversation_id: The ID of the conversation to send the message to
        request: The HTTP request containing the message data
        current_user: The authenticated user making the request
        
    Returns:
        dict: Message ID, timestamp, and status
        
    Raises:
        400: If content is missing or message type is invalid
        403: If the user is not a participant in the conversation
        404: If the conversation doesn't exist
    """
    # Parse request data
    try:
        data = await request.json()
    except Exception as e:
        logger.error(f"Error parsing request body: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid request body")

    content = data.get('content')
    message_type = data.get('messageType', 'text')

    # Validate request data
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    # Validate message type
    if message_type not in [m.value for m in MessageType]:
        raise HTTPException(status_code=400,
                            detail=f"Invalid message type. Must be one of: {[m.value for m in MessageType]}")

    # Verify conversation exists and user is a participant
    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = conversation_ref.get()

    if not conversation.exists:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_data = conversation.to_dict()
    if current_user.phoneNumber not in conversation_data.get('participants', []):
        raise HTTPException(status_code=403, detail="User is not a participant in this conversation")

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

    # Store message in Firestore
    try:
        message_ref = firestore_db.collection('conversations').document(conversation_id).collection(
            'messages').document(message_id)
        message_ref.set(message_data)

        # Update conversation's last message info
        conversation_ref.update({
            'lastMessageTime': firestore.SERVER_TIMESTAMP,
            'lastMessagePreview': content[:50] + ('...' if len(content) > 50 else '')
        })
    except Exception as e:
        logger.error(f"Error storing message in Firestore: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to send message")

    # Send real-time notifications via WebSocket
    try:
        await broadcast_message(conversation_id, message_id, current_user.phoneNumber, content, message_type)
    except Exception as e:
        logger.error(f"Error broadcasting message via WebSocket: {str(e)}")
        # Don't fail the request if WebSocket notification fails

    # Send push notifications
    try:
        participants = conversation_data.get('participants', [])
        notification_sent = False

        # Try SQS if available
        if is_sqs_available():
            try:
                notification_sent = await send_chat_message_notification(
                    chat_id=conversation_id,  # SQS utility still uses chat_id parameter name
                    message_id=message_id,
                    sender_id=current_user.phoneNumber,
                    content=content,
                    message_type=message_type,
                    participants=participants
                )

                if notification_sent:
                    logger.info(f"Notification for message {message_id} sent to SQS queue")
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
                    'conversationId': conversation_id,  # Updated to use conversationId
                    'messageId': message_id,
                    'senderId': current_user.phoneNumber,
                    'content': content,
                    'messageType': message_type,
                    'timestamp': now.isoformat(),
                    'participants': participants
                }

                # Process notification directly (asynchronously)
                asyncio.create_task(notification_service.process_new_message(notification_data))
            except Exception as e:
                logger.error(f"Error in direct notification processing: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing notifications: {str(e)}")
        # Don't fail the request if notification processing fails

    return {
        'messageId': message_id,
        'timestamp': now.isoformat(),
        'status': 'sent'
    }


@router.post('/{conversation_id}/messages/{message_id}/read')
async def mark_message_as_read(
        conversation_id: str,
        message_id: str,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Mark a message as read by the current user
    
    Args:
        conversation_id: The ID of the conversation containing the message
        message_id: The ID of the message to mark as read
        current_user: The authenticated user making the request
        
    Returns:
        dict: Success status
        
    Raises:
        403: If the user is not a participant in the conversation
        404: If the conversation or message doesn't exist
    """
    # Verify user is part of this conversation
    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = conversation_ref.get()

    if not conversation.exists:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation_data = conversation.to_dict()
    if current_user.phoneNumber not in conversation_data.get('participants', []):
        raise HTTPException(status_code=403, detail="User is not a participant in this conversation")

    # Get the message
    message_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages').document(
        message_id)
    message = message_ref.get()

    if not message.exists:
        raise HTTPException(status_code=404, detail="Message not found")

    message_data = message.to_dict()
    read_by = message_data.get('readBy', [])

    # Add user to readBy if not already there
    if current_user.phoneNumber not in read_by:
        read_by.append(current_user.phoneNumber)
        message_ref.update({'readBy': read_by})

    # Notify other participants via WebSocket that message has been read
    try:
        read_event = {
            'event': 'message_read',
            'conversationId': conversation_id,
            'messageId': message_id,
            'userId': current_user.phoneNumber
        }
        await connection_manager.broadcast_to_conversation(read_event, conversation_id,
                                                           skip_user_id=current_user.phoneNumber)
    except Exception as e:
        logger.error(f"Error broadcasting read receipt: {str(e)}")
        # Don't fail the request if WebSocket notification fails

    return {'status': 'success'}


async def broadcast_message(conversation_id: str, message_id: str, sender_id: str, content: str, message_type: str):
    """
    Broadcast a message to all participants in a conversation
    
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
