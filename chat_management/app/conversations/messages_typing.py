import json
import logging
import os
import socket
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user, verify_conversation_participant
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

# Add a REST API endpoint for typing indicators
@router.post('/conversations/{conversation_id}/typing', tags=tags,
             dependencies=[Depends(verify_conversation_participant)])
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