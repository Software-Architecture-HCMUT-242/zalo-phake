import asyncio
import json
import logging
import os
import socket
from typing import Dict, Any

from .connection import get_redis_connection
from ..ws.websocket_manager import get_connection_manager

logger = logging.getLogger(__name__)

async def handle_new_message(data: Dict[str, Any], connection_manager):
    """
    Process new message events from Redis PubSub
    
    Args:
        data: Message data containing conversationId, message details
        connection_manager: WebSocket connection manager instance
    """
    try:
        conversation_id = data.get('conversationId')
        sender_id = data.get('senderId')
        
        if not conversation_id or not sender_id:
            logger.error(f"Missing required fields in new_message event: {data}")
            return
            
        # Forward message to all local connections for this conversation
        await connection_manager.broadcast_to_conversation(data, conversation_id, skip_user_id=sender_id)
        logger.debug(f"Forwarded new message in conversation {conversation_id} from user {sender_id}")
        
    except Exception as e:
        logger.error(f"Error handling new message event: {str(e)}")

async def handle_typing(data: Dict[str, Any], connection_manager):
    """
    Process typing indicator events from Redis PubSub
    
    Args:
        data: Typing data containing conversationId and userId
        connection_manager: WebSocket connection manager instance
    """
    try:
        conversation_id = data.get('conversationId')
        user_id = data.get('userId')
        
        if not conversation_id or not user_id:
            logger.error(f"Missing required fields in typing event: {data}")
            return
            
        # Forward typing indicator to all local connections for this conversation
        await connection_manager.broadcast_to_conversation(data, conversation_id, skip_user_id=user_id)
        logger.debug(f"Forwarded typing indicator in conversation {conversation_id} from user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling typing event: {str(e)}")

async def handle_read_receipt(data: Dict[str, Any], connection_manager):
    """
    Process read receipt events from Redis PubSub
    
    Args:
        data: Read receipt data containing conversationId, messageId and userId
        connection_manager: WebSocket connection manager instance
    """
    try:
        conversation_id = data.get('conversationId')
        message_id = data.get('messageId')
        user_id = data.get('userId')
        
        if not conversation_id or not message_id or not user_id:
            logger.error(f"Missing required fields in message_read event: {data}")
            return
            
        # Forward read receipt to all local connections for this conversation
        await connection_manager.broadcast_to_conversation(data, conversation_id, skip_user_id=user_id)
        logger.debug(f"Forwarded read receipt in conversation {conversation_id} for message {message_id} from user {user_id}")
        
    except Exception as e:
        logger.error(f"Error handling read receipt event: {str(e)}")

async def handle_status_change(data: Dict[str, Any], connection_manager):
    """
    Process user status change events from Redis PubSub
    
    Args:
        data: Status data containing userId and status
        connection_manager: WebSocket connection manager instance
    """
    try:
        user_id = data.get('userId')
        status = data.get('status')
        
        if not user_id or not status:
            logger.error(f"Missing required fields in user_status_change event: {data}")
            return
            
        # Forward status change to relevant conversations
        # This needs conversation IDs, which we might need to get from Firestore
        # For now, we'll forward to all local connections that need to know about this user
        if 'conversationId' in data:
            # If conversation ID is provided, broadcast to that conversation
            await connection_manager.broadcast_to_conversation(data, data['conversationId'], skip_user_id=user_id)
        else:
            # Otherwise, send to all relevant users (handled by ws manager)
            await connection_manager.broadcast_user_status(user_id, status)
            
        logger.debug(f"Forwarded status change for user {user_id} to status {status}")
        
    except Exception as e:
        logger.error(f"Error handling status change event: {str(e)}")

async def start_pubsub_listener():
    """
    Start the Redis PubSub listener for inter-instance communication
    
    This function runs as a background task and continuously listens for
    messages published to channels that this instance is subscribed to.
    """
    instance_id = os.environ.get("INSTANCE_ID", socket.gethostname())
    connection_manager = get_connection_manager()
    
    # Map of event types to handler functions
    event_handlers = {
        'new_message': handle_new_message,
        'typing': handle_typing,
        'message_read': handle_read_receipt,
        'user_status_change': handle_status_change
    }
    
    # Reconnection parameters
    max_retries = 5
    retry_delay = 5  # seconds
    current_retry = 0
    
    while True:
        try:
            redis_conn = await get_redis_connection()
            pubsub = redis_conn.pubsub()
            
            # Subscribe to all channels relevant to this instance
            # In production, you would have a mechanism to register subscriptions
            # when users connect. For now, using a simple approach.
            instance_channels_key = f"subscriptions:{instance_id}"
            
            channels = await redis_conn.smembers(instance_channels_key)
            if not channels:
                logger.warning(f"No channels found for instance {instance_id}. Will check again in 5 seconds.")
                await asyncio.sleep(5)
                continue
            
            await pubsub.subscribe(*channels)
            logger.info(f"PubSub listener started for instance {instance_id} with {len(channels)} channels")
            
            # Reset retry counter on successful connection
            current_retry = 0
            
            # Listen for messages
            async for message in pubsub.listen():
                if message['type'] != 'message':
                    continue
                
                try:
                    channel = message['channel']
                    data = json.loads(message['data'])
                    
                    # Extract event type and call the appropriate handler
                    event_type = data.get('event')
                    if event_type in event_handlers:
                        await event_handlers[event_type](data, connection_manager)
                    else:
                        logger.warning(f"Unknown event type: {event_type}")
                    
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in Redis message: {message['data']}")
                except Exception as e:
                    logger.error(f"Error processing Redis message: {str(e)}")
        
        except Exception as e:
            logger.error(f"PubSub listener error: {str(e)}")
            
            # Implement retry logic
            current_retry += 1
            if current_retry <= max_retries:
                retry_wait = retry_delay * current_retry
                logger.info(f"Retrying PubSub connection in {retry_wait} seconds (attempt {current_retry}/{max_retries})")
                await asyncio.sleep(retry_wait)
            else:
                logger.critical(f"Failed to connect to Redis after {max_retries} attempts. PubSub listener stopped.")
                # In production, you might want to implement a circuit breaker pattern here
                # For now, we'll just reset and try again after a longer delay
                current_retry = 0
                await asyncio.sleep(60)  # Wait a minute before trying again
