import asyncio
import json
import logging
import os
import socket
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import firestore

from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user, verify_conversation_participant
from ..firebase import firestore_db
from ..notifications.service import NotificationService
from ..redis.connection import get_redis_connection
from ..ws.router import get_connection_manager

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(decode_token)],
)

notification_service = NotificationService()
connection_manager = get_connection_manager()
tags = ["Messages"]

@router.post('/conversations/{conversation_id}/messages/{message_id}/read',
             tags=tags,
             dependencies=[Depends(verify_conversation_participant)])
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
            
            # Update the unread count for the user in this conversation
            try:
                user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                                .collection('user_stats').document(user_id)
                
                # Get current unread count
                user_stats = await asyncio.to_thread(user_stats_ref.get)
                if user_stats.exists:
                    unread_count = user_stats.to_dict().get('unreadCount', 0)
                    if unread_count > 0:  # Ensure we don't go below zero
                        await asyncio.to_thread(user_stats_ref.update, {'unreadCount': unread_count - 1})
                        logger.info(f"Decremented unread count for user {user_id} in conversation {conversation_id} to {unread_count - 1}")
            except Exception as e:
                logger.error(f"Error updating unread count: {str(e)}")
                # Don't fail the overall request if updating unread count fails
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


# Endpoint to mark all messages in a conversation as read
@router.post('/conversations/{conversation_id}/mark_all_read', tags=tags,
             dependencies=[Depends(verify_conversation_participant)])
async def mark_all_messages_as_read(
        conversation_id: str,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Mark all messages in a conversation as read by the current user
    
    Args:
        conversation_id: The ID of the conversation containing the messages
        current_user: The authenticated user making the request
        
    Returns:
        dict: Success status with count of newly read messages
        
    Raises:
        403: If the user is not a participant in the conversation
        404: If the conversation doesn't exist
        500: If there's a database or other error
    """
    user_id = current_user.phoneNumber
    
    # Get all messages that the user hasn't read yet
    try:
        # Query messages that don't have the user in readBy array
        messages_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages')
        query = messages_ref.where('readBy', 'array_contains', user_id).limit(1)
        
        # Use a Firestore batch to update all messages at once
        batch = firestore_db.batch()
        message_updates = 0
        
        # Get all unread messages
        unread_messages = []
        
        # Query in batches to avoid hitting Firestore limits
        async def get_unread_messages():
            nonlocal unread_messages
            # This array query has to be inverted - we need to get all messages and filter
            all_messages = await asyncio.to_thread(messages_ref.get)
            
            for msg in all_messages:
                msg_data = msg.to_dict()
                read_by = msg_data.get('readBy', [])
                if user_id not in read_by:
                    unread_messages.append((msg.id, msg_data))
        
        await get_unread_messages()
        
        # No unread messages
        if not unread_messages:
            # Reset unread count to ensure consistency
            user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                            .collection('user_stats').document(user_id)
            await asyncio.to_thread(user_stats_ref.update, {'unreadCount': 0})
            return {'status': 'success', 'messagesRead': 0}
        
        # Update all unread messages
        for msg_id, msg_data in unread_messages:
            msg_ref = messages_ref.document(msg_id)
            read_by = msg_data.get('readBy', [])
            read_by.append(user_id)
            batch.update(msg_ref, {'readBy': read_by})
            message_updates += 1
        
        # Commit the batch
        await asyncio.to_thread(batch.commit)
        logger.info(f"Marked {message_updates} messages as read for user {user_id} in conversation {conversation_id}")
        
        # Update unread count to zero
        user_stats_ref = firestore_db.collection('conversations').document(conversation_id) \
                        .collection('user_stats').document(user_id)
        await asyncio.to_thread(user_stats_ref.update, {'unreadCount': 0})
        logger.info(f"Reset unread count to 0 for user {user_id} in conversation {conversation_id}")
        
        # Notify other participants
        try:
            redis_conn = await get_redis_connection()
            
            # Create bulk read receipt event
            read_event = {
                'event': 'conversation_read',
                'conversationId': conversation_id,
                'userId': user_id,
                'count': message_updates,
                'instanceId': os.environ.get("INSTANCE_ID", socket.gethostname())
            }
            
            # Publish to Redis channel
            channel = f"conversation:{conversation_id}"
            await redis_conn.publish(channel, json.dumps(read_event))
        except Exception as e:
            logger.error(f"Error publishing bulk read receipt to Redis: {str(e)}")
        
        return {'status': 'success', 'messagesRead': message_updates}
        
    except Exception as e:
        logger.error(f"Error marking all messages as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark all messages as read"
        )
