import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket
from firebase_admin import firestore


from .schemas import Message, MessageType
from ..aws.sqs_utils import is_sqs_available, send_chat_message_notification
from ..dependencies import token_required, AuthenticatedUser, get_current_active_user
from ..firebase import firestore_db
from ..notifications.service import NotificationService
from ..pagination import PaginatedResponse, PaginationParams, common_pagination_parameters
from ..time_utils import convert_timestamps

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(token_required)],
)

notification_service = NotificationService()

# Store active WebSocket connections
active_connections: Dict[str, Dict[str, WebSocket]] = {}

@router.get('/conversations/{chat_id}/messages', response_model=PaginatedResponse[Message])
async def get_messages(chat_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(common_pagination_parameters)]):
    """
    Get paginated messages for a specific chat
    """
    # Verify user is part of this chat
    chat_ref = firestore_db.collection('conversations').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat.to_dict()
    if current_user.phoneNumber not in chat_data.get('participants', []):
        raise HTTPException(status_code=403, detail="User is not a participant in this chat")

    # Query messages for this chat
    messages_ref = firestore_db.collection('conversations').document(chat_id).collection('messages')
    query = messages_ref.order_by('timestamp', direction='DESCENDING')

    # Get total count for pagination
    total_docs = query.get()
    total_messages = len(total_docs)

    # Apply pagination
    paginated_msgs = query.offset((pagination.page - 1) * pagination.size).limit(pagination.size).get()

    messages = []
    for msg in paginated_msgs:
        msg_data = msg.to_dict()
        # Convert timestamps
        msg_data = convert_timestamps(msg_data)
        messages.append(Message(
            messageId=msg.id,
            senderId=msg_data.get('senderId'),
            content=msg_data.get('content'),
            messageType=msg_data.get('messageType', MessageType.TEXT),
            timestamp=msg_data.get('timestamp', datetime.now(timezone.utc)),
            readBy=msg_data.get('readBy', [])
        ))

    return PaginatedResponse.create(
        items=messages,
        total=total_messages,
        page=pagination.page,
        size=pagination.size
    )

@router.post('/conversations/{chat_id}/messages/{message_id}/read')
async def mark_message_as_read(
    chat_id: str,
    message_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Mark a message as read by the current user
    """
    # Verify user is part of this chat
    chat_ref = firestore_db.collection('conversations').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat.to_dict()
    if current_user.phoneNumber not in chat_data.get('participants', []):
        raise HTTPException(status_code=403, detail="User is not a participant in this chat")

    # Get the message
    message_ref = firestore_db.collection('conversations').document(chat_id).collection('messages').document(message_id)
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
    read_event = {
        'event': 'message_read',
        'chatId': chat_id,
        'messageId': message_id,
        'userId': current_user.phoneNumber
    }
    await broadcast_event(chat_id, read_event, current_user.phoneNumber)

    return {'status': 'success'}

@router.post('/conversations/{chat_id}/messages')
async def send_message(
    chat_id: str,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Send a message to a specific chat
    """
    data = await request.json()
    content = data.get('content')
    message_type = data.get('messageType', 'text')

    if not content:
        raise HTTPException(status_code=400, detail="Content is required")

    # Validate message type
    if message_type not in [m.value for m in MessageType]:
        raise HTTPException(status_code=400, detail=f"Invalid message type. Must be one of: {[m.value for m in MessageType]}")

    # Verify user is part of this chat
    chat_ref = firestore_db.collection('conversations').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = chat.to_dict()
    if current_user.phoneNumber not in chat_data.get('participants', []):
        raise HTTPException(status_code=403, detail="User is not a participant in this chat")

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
    message_ref = firestore_db.collection('conversations').document(chat_id).collection('messages').document(message_id)
    message_ref.set(message_data)

    # Update chat's last message info
    chat_ref.update({
        'lastMessageTime': firestore.SERVER_TIMESTAMP,
        'lastMessagePreview': content[:50] + ('...' if len(content) > 50 else '')
    })

    # Send message via WebSocket to connected participants
    await broadcast_message(chat_id, message_id, current_user.phoneNumber, content, message_type)

    # Send notification using SQS utils if available
    participants = chat_data.get('participants', [])
    notification_sent = False

    if is_sqs_available():
        try:
            # Use the utility function to send notification through SQS
            notification_sent = await send_chat_message_notification(
                chat_id=chat_id,
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

    # If SQS is not available or notification failed, try direct processing
    # This ensures notifications work even if SQS is down
    if not notification_sent:
        logger.info("Using direct notification processing as fallback")
        try:
            # Prepare message for direct notification processing
            notification_data = {
                'event': 'new_message',
                'chatId': chat_id,
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

    return {
        'messageId': message_id,
        'timestamp': now.isoformat(),
        'status': 'sent'
    }

async def broadcast_message(chat_id: str, message_id: str, sender_id: str, content: str, message_type: str):
    """
    Broadcast a message to all participants in a chat
    """
    # Get chat participants
    chat_ref = firestore_db.collection('conversations').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
        logger.error(f"Chat {chat_id} not found for broadcasting")
        return

    participants = chat.to_dict().get('participants', [])
    message = {
        'event': 'new_message',
        'chatId': chat_id,
        'messageId': message_id,
        'senderId': sender_id,
        'content': content,
        'messageType': message_type,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }

    # Send to all connected participants except the sender
    for participant in participants:
        if participant == sender_id:
            continue

        if participant in active_connections:
            message_json = json.dumps(message)
            for connection in active_connections[participant].values():
                try:
                    await connection.send_text(message_json)
                    logger.debug(f"WebSocket message sent to {participant}")
                except Exception as e:
                    logger.error(f"Error sending WebSocket message to {participant}: {str(e)}")

async def broadcast_event(chat_id: str, event: dict, sender_id: str):
    """
    Broadcast an event to all participants in a chat
    """
    # Get chat participants
    chat_ref = firestore_db.collection('conversations').document(chat_id)
    chat = chat_ref.get()

    if not chat.exists:
        logger.error(f"Chat {chat_id} not found for broadcasting event")
        return

    participants = chat.to_dict().get('participants', [])
    event_json = json.dumps(event)

    # Send to all connected participants except the sender
    for participant in participants:
        if participant == sender_id:
            continue

        if participant in active_connections:
            for connection in active_connections[participant].values():
                try:
                    await connection.send_text(event_json)
                    logger.debug(f"WebSocket event sent to {participant}")
                except Exception as e:
                    logger.error(f"Error sending WebSocket event to {participant}: {str(e)}")