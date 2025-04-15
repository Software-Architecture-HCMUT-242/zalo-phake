import asyncio
import json
import logging
import time
import uuid
from typing import Dict, Optional, Set, Any

from fastapi import WebSocket
from firebase_admin import firestore

from ..firebase import firestore_db
from ..redis.connection import get_redis_connection

logger = logging.getLogger(__name__)

# Global connection manager instance
connection_manager = None

# Function to get the connection manager singleton
def get_connection_manager():
  global connection_manager
  if connection_manager is None:
    connection_manager = ConnectionManager()
  return connection_manager

class ConnectionManager:
  def __init__(self):
    self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
    self.user_conversations: Dict[str, Set[str]] = {}  # Maps user IDs to their conversation IDs
    self.instance_id = uuid.uuid4().hex  # Generate a unique ID for this instance

  async def connect(self, websocket: WebSocket, user_id: str):
    """
    Connect a new WebSocket client
    """
    await websocket.accept()

    # Initialize user's connections if not exists
    if user_id not in self.active_connections:
      self.active_connections[user_id] = {}
      self.user_conversations[user_id] = set()

    # Generate a connection ID for this specific connection
    connection_id = str(uuid.uuid4())
    self.active_connections[user_id][connection_id] = websocket

    # Update user status to online in Firestore
    try:
      user_ref = firestore_db.collection('users').document(user_id)
      user_ref.update({
        'isOnline': True,
        'lastActive': firestore.SERVER_TIMESTAMP
      })
      logger.info(f"User {user_id} connected with connection ID {connection_id}")
    except Exception as e:
      logger.error(f"Error updating online status: {str(e)}")

    return connection_id

  def disconnect(self, user_id: str, connection_id: str):
    """
    Disconnect a WebSocket client
    """
    if user_id in self.active_connections and connection_id in self.active_connections[user_id]:
      del self.active_connections[user_id][connection_id]
      logger.info(f"User {user_id} disconnected connection ID {connection_id}")

      # If this was the last connection for this user, clean up
      if not self.active_connections[user_id]:
        del self.active_connections[user_id]
        if user_id in self.user_conversations:
          del self.user_conversations[user_id]
        logger.info(f"User {user_id} has no more active connections")
        return True  # All connections closed

    return False  # User still has other connections

  async def set_offline_status(self, user_id: str):
    """
    Set user status to offline with a delay
    """
    try:
      await asyncio.sleep(60)  # 60-second grace period

      # Check if the user still has no connections
      if user_id not in self.active_connections:
        user_ref = firestore_db.collection('users').document(user_id)
        user_ref.update({
          'isOnline': False,
          'lastActive': firestore.SERVER_TIMESTAMP
        })
        logger.info(f"User {user_id} status set to offline after grace period")
    except Exception as e:
      logger.error(f"Error updating offline status: {str(e)}")

  async def send_personal_message(self, message: dict, user_id: str):
    """
    Send a message to a specific user's all connections
    """
    if user_id in self.active_connections:
      disconnected = []
      message_json = json.dumps(message)

      for connection_id, websocket in self.active_connections[user_id].items():
        try:
          await websocket.send_text(message_json)
        except Exception as e:
          logger.error(f"Error sending message to {user_id} connection {connection_id}: {str(e)}")
          disconnected.append((user_id, connection_id))

      # Clean up any disconnected websockets
      for user_id, connection_id in disconnected:
        self.disconnect(user_id, connection_id)

  async def broadcast_to_conversation(self, message: dict, conversation_id: str, skip_user_id: Optional[str] = None):
    """
    Broadcast a message to all participants in a conversation
    """
    try:
      # Get conversation participants from Firestore
      conversation_ref = firestore_db.collection('conversations').document(conversation_id)
      conversation = conversation_ref.get()

      if not conversation.exists:
        logger.error(f"Conversation {conversation_id} not found for broadcasting")
        return

      participants = conversation.to_dict().get('participants', [])
      message_json = json.dumps(message)

      # Track users to disconnect
      disconnected = []

      # Send to all connected participants except the sender
      for participant in participants:
        if participant == skip_user_id:
          continue

        if participant in self.active_connections:
          # Add conversation to user's conversation set
          if participant in self.user_conversations:
            self.user_conversations[participant].add(conversation_id)

          # Send to all connections for this user
          for connection_id, websocket in self.active_connections[participant].items():
            try:
              await websocket.send_text(message_json)
            except Exception as e:
              logger.error(f"Error broadcasting to {participant} connection {connection_id}: {str(e)}")
              disconnected.append((participant, connection_id))

      # Clean up any disconnected websockets
      for user_id, connection_id in disconnected:
        self.disconnect(user_id, connection_id)

    except Exception as e:
      logger.error(f"Error in broadcast_to_conversation: {str(e)}")

  async def handle_typing_notification(self, conversation_id: str, user_id: str):
    """
    Broadcast typing notification to conversation participants
    
    Args:
        conversation_id: The ID of the conversation where typing is occurring
        user_id: The ID of the user who is typing
    """
    typing_event = {
      'event': 'typing',
      'conversationId': conversation_id,
      'userId': user_id
    }
    await self.broadcast_to_conversation(typing_event, conversation_id, skip_user_id=user_id)

  async def handle_read_receipt(self, conversation_id: str, message_id: str, user_id: str):
    """
    Broadcast read receipt to conversation participants and update message status in database
    
    Args:
        conversation_id: The ID of the conversation containing the message
        message_id: The ID of the message that was read
        user_id: The ID of the user who read the message
    """
    # Update the message read status in Firestore
    try:
      # Get the message reference
      message_ref = firestore_db.collection('conversations').document(conversation_id) \
                               .collection('messages').document(message_id)
      
      # Update the read status in a transaction to ensure consistency
      @firestore.transactional
      def update_read_status(transaction, message_ref):
        message = message_ref.get(transaction=transaction)
        if not message.exists:
          logger.error(f"Message {message_id} not found in conversation {conversation_id}")
          return False
        
        message_data = message.to_dict()
        read_by = message_data.get('readBy', [])
        
        # Only update if the user hasn't already read the message
        if user_id not in read_by:
          read_by.append(user_id)
          transaction.update(message_ref, {'readBy': read_by})
          logger.info(f"Updated read status for message {message_id} by user {user_id}")
          return True
        return False
      
      # Execute the transaction
      transaction = firestore_db.transaction()
      was_updated = update_read_status(transaction, message_ref)
      
      # Broadcast read receipt to other participants if status was updated
      if was_updated:
        read_event = {
          'event': 'message_read',
          'conversationId': conversation_id,
          'messageId': message_id,
          'userId': user_id
        }
        await self.broadcast_to_conversation(read_event, conversation_id, skip_user_id=user_id)
      
    except Exception as e:
      logger.error(f"Error updating read receipt in database: {str(e)}")
      # Still broadcast the event even if database update fails
      read_event = {
        'event': 'message_read',
        'conversationId': conversation_id,
        'messageId': message_id,
        'userId': user_id
      }
      await self.broadcast_to_conversation(read_event, conversation_id, skip_user_id=user_id)

  def get_user_connection_count(self, user_id: str) -> int:
    """
    Get the number of active connections for a user
    """
    if user_id in self.active_connections:
      return len(self.active_connections[user_id])
    return 0

  def is_user_connected(self, user_id: str) -> bool:
    """
    Check if a user has any active connections
    """
    return user_id in self.active_connections and len(self.active_connections[user_id]) > 0

  def get_connected_users_count(self) -> int:
    """
    Get the total number of connected users
    """
    return len(self.active_connections)

  def get_total_connections_count(self) -> int:
    """
    Get the total number of WebSocket connections on this instance
    
    Returns:
        int: Total number of active connections
    """
    return sum(len(connections) for connections in self.active_connections.values())
    
  async def handle_user_activity(self, user_id: str, activity_type: str, metadata: dict = None):
    """
    Update user activity status and broadcast if necessary
    
    Args:
        user_id: The ID of the user performing the activity
        activity_type: Type of activity (e.g., 'status_change', 'profile_update')
        metadata: Additional information about the activity
    """
    if not metadata:
      metadata = {}
    
    logger.info(f"Handling user activity: {activity_type} for user {user_id}")
    
    try:
      # Update user activity timestamp in Firestore
      user_ref = firestore_db.collection('users').document(user_id)
      update_data = {
        'lastActive': firestore.SERVER_TIMESTAMP,
        'lastActivityType': activity_type
      }
      
      # If this is a status change, update the status field
      if activity_type == 'status_change' and 'status' in metadata:
        update_data['status'] = metadata['status']
      
      # Update in Firestore
      await asyncio.to_thread(user_ref.update, update_data)
      
      # If this is a status change, broadcast to relevant conversations
      if activity_type == 'status_change' and 'status' in metadata:
        status_event = {
          'event': 'user_status_change',
          'userId': user_id,
          'status': metadata['status']
        }
        
        # Get all conversations this user participates in
        conversations = await self.get_user_conversations(user_id)
        
        # Get Redis connection for publishing
        redis_conn = await get_redis_connection()
        
        # Broadcast status change to all conversations
        for conversation_id in conversations:
          channel = f"conversation:{conversation_id}"
          await redis_conn.publish(channel, json.dumps(status_event))
          
        logger.info(f"Broadcast status change for user {user_id} to {len(conversations)} conversations")
          
    except Exception as e:
      logger.error(f"Error handling user activity: {str(e)}")
  
  async def get_user_conversations(self, user_id: str) -> set:
    """
    Get all conversations that a user participates in
    
    Args:
        user_id: The ID of the user
        
    Returns:
        set: Set of conversation IDs the user participates in
    """
    try:
      # Check if we already have the user's conversations cached
      if user_id in self.user_conversations and self.user_conversations[user_id]:
        return self.user_conversations[user_id]
      
      # Otherwise, query Firestore for the user's conversations
      conversations = set()
      
      # Query conversations where user is a participant
      conversations_ref = firestore_db.collection('conversations')
      query = conversations_ref.where('participants', 'array_contains', user_id)
      
      # Execute query
      conversation_docs = await asyncio.to_thread(query.get)
      
      # Extract conversation IDs
      for doc in conversation_docs:
        conversations.add(doc.id)
      
      # Cache the result
      self.user_conversations[user_id] = conversations
      
      logger.debug(f"Loaded {len(conversations)} conversations for user {user_id}")
      return conversations
      
    except Exception as e:
      logger.error(f"Error getting user conversations: {str(e)}")
      return set()
  
  async def broadcast_user_status(self, user_id: str, status: str):
    """
    Broadcast a user's status change to relevant local connections
    
    This is a helper method used when receiving status change events from Redis.
    It delivers the event to local connections that need to know about this user.
    
    Args:
        user_id: The ID of the user whose status changed
        status: The new status value
    """
    try:
      # Get all conversations this user participates in
      conversations = await self.get_user_conversations(user_id)
      
      # For each conversation, deliver status update to other participants
      for conversation_id in conversations:
        # Get conversation participants
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = await asyncio.to_thread(conversation_ref.get)
        
        if not conversation.exists:
          continue
          
        participants = conversation.to_dict().get('participants', [])
        
        # Prepare status change message
        message = {
          'event': 'user_status_change',
          'userId': user_id,
          'status': status,
          'conversationId': conversation_id
        }
        message_json = json.dumps(message)
        
        # Track disconnections
        disconnected = []
        
        # Send to all local participants (except the user whose status changed)
        for participant in participants:
          if participant == user_id:
            continue
            
          if participant in self.active_connections:
            # Send to all connections for this participant
            for connection_id, websocket in self.active_connections[participant].items():
              try:
                await websocket.send_text(message_json)
                logger.debug(f"Sent status update about {user_id} to {participant}")
              except Exception as e:
                logger.error(f"Error sending status update to {participant}: {str(e)}")
                disconnected.append((participant, connection_id))
        
        # Clean up disconnected connections
        for user_id, connection_id in disconnected:
          self.disconnect(user_id, connection_id)
          
    except Exception as e:
      logger.error(f"Error broadcasting user status: {str(e)}")
  
  async def get_connection_stats(self) -> Dict[str, Any]:
    """
    Get statistics about current WebSocket connections
    
    Returns:
        Dict: Connection statistics
    """
    try:
      # Get local connection counts
      local_users = len(self.active_connections)
      local_connections = self.get_total_connections_count()
      
      # Get global connection counts from Redis
      redis_conn = await get_redis_connection()
      
      # Get all user keys
      all_user_keys = await redis_conn.keys("connections:*")
      global_users = len(all_user_keys)
      
      # Count all connections across instances
      global_connections = 0
      for user_key in all_user_keys:
        connections = await redis_conn.hlen(user_key)
        global_connections += connections
      
      return {
        "instance_id": self.instance_id,
        "local_users": local_users,
        "local_connections": local_connections,
        "global_users": global_users,
        "global_connections": global_connections,
        "timestamp": time.time()
      }
    except Exception as e:
      logger.error(f"Error getting connection stats: {str(e)}")
      return {
        "instance_id": self.instance_id,
        "error": str(e),
        "local_users": len(self.active_connections),
        "local_connections": self.get_total_connections_count(),
        "timestamp": time.time()
      }