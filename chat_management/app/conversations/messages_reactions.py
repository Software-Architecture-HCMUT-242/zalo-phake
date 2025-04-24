import asyncio
import json
import logging
import os
import socket
from typing import Annotated, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import firestore

from .schemas import MessageReactionRequest, MessageReactionResponse
from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user, verify_conversation_participant
from ..firebase import firestore_db
from ..redis.connection import get_redis_connection
from ..ws.router import get_connection_manager

logger = logging.getLogger(__name__)

# Create router with token dependency
router = APIRouter(
    dependencies=[Depends(decode_token)],
)

connection_manager = get_connection_manager()
tags = ["Messages"]

@router.post('/conversations/{conversation_id}/messages/{message_id}/reactions',
             response_model=MessageReactionResponse,
             tags=tags,
             dependencies=[Depends(verify_conversation_participant)])
async def add_message_reaction(
        conversation_id: str,
        message_id: str,
        reaction_data: MessageReactionRequest,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Add, update, or remove a reaction to a specific message.
    
    Args:
        conversation_id: The ID of the conversation containing the message
        message_id: The ID of the message to react to
        reaction_data: The reaction data (emoji or null to remove)
        current_user: The authenticated user making the request
        
    Returns:
        MessageReactionResponse: The message ID and updated reactions map
        
    Raises:
        404: If the conversation or message doesn't exist
        403: If the user is not a participant in the conversation
        500: If there's a database or other error
    """
    # Get the message reference
    message_ref = firestore_db.collection('conversations').document(conversation_id) \
                   .collection('messages').document(message_id)
    
    try:
        # Get the message
        message = await asyncio.to_thread(message_ref.get)
        if not message.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
        
        # Get the reaction
        reaction = reaction_data.reaction
        user_id = current_user.phoneNumber
        
        # Update the message's reactions field
        if reaction and reaction.strip():
            # Add or update reaction
            update_data = {
                f'reactions.{user_id}': reaction.strip()
            }
            await asyncio.to_thread(message_ref.update, update_data)
            logger.info(f"User {user_id} added reaction '{reaction}' to message {message_id}")
        else:
            # Remove reaction if it exists
            message_data = message.to_dict()
            reactions = message_data.get('reactions', {})
            
            if user_id in reactions:
                # Use FieldValue.delete() to remove the specific field
                await asyncio.to_thread(
                    message_ref.update,
                    {f'reactions.{user_id}': firestore.DELETE_FIELD}
                )
                logger.info(f"User {user_id} removed reaction from message {message_id}")
            else:
                logger.info(f"No reaction to remove for user {user_id} on message {message_id}")
        
        # Get the updated message to return current reactions
        updated_message = await asyncio.to_thread(message_ref.get)
        updated_data = updated_message.to_dict()
        reactions = updated_data.get('reactions', {})
        
        # If reactions is None, initialize as empty dict
        if reactions is None:
            reactions = {}
        
        # Publish reaction event to Redis for real-time notifications
        try:
            redis_conn = await get_redis_connection()
            
            # Create reaction event data for publishing
            reaction_event = {
                'event': 'message_reaction',
                'conversationId': conversation_id,
                'messageId': message_id,
                'userId': user_id,
                'reaction': reaction,
                'instanceId': os.environ.get("INSTANCE_ID", socket.gethostname())
            }
            
            # Publish to Redis channel for this conversation
            channel = f"conversation:{conversation_id}"
            pub_result = await redis_conn.publish(channel, json.dumps(reaction_event))
            
            if pub_result:
                logger.info(f"Reaction event published to Redis channel {channel} with {pub_result} receivers")
            else:
                logger.warning(f"Published to Redis channel {channel} but found no subscribers")
                # Try direct WebSocket broadcast as fallback
                try:
                    await connection_manager.broadcast_to_conversation(
                        reaction_event, conversation_id, skip_user_id=user_id
                    )
                except Exception as ws_error:
                    logger.error(f"Error broadcasting reaction via WebSocket fallback: {str(ws_error)}")
        except Exception as e:
            logger.error(f"Error with Redis Pub/Sub for reaction event: {str(e)}")
            # Try direct WebSocket broadcast as fallback
            try:
                reaction_event = {
                    'event': 'message_reaction',
                    'conversationId': conversation_id,
                    'messageId': message_id,
                    'userId': user_id,
                    'reaction': reaction
                }
                await connection_manager.broadcast_to_conversation(
                    reaction_event, conversation_id, skip_user_id=user_id
                )
            except Exception as ws_error:
                logger.error(f"Error broadcasting reaction via WebSocket fallback: {str(ws_error)}")
        
        # Return the successful response
        return MessageReactionResponse(
            messageId=message_id,
            reactions=reactions
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions directly
        raise
    except Exception as e:
        logger.error(f"Error processing message reaction: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error processing message reaction"
        )
