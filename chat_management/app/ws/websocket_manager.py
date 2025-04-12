import json
import logging
import asyncio
from typing import Dict, List, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect
import uuid
from firebase_admin import firestore
from ..firebase import firestore_db

logger = logging.getLogger(__name__)

class ConnectionManager:
  def __init__(self):
    self.active_connections: Dict[str, Dict[str, WebSocket]] = {}
    self.user_chats: Dict[str, Set[str]] = {}  # Maps user IDs to their chat IDs

  async def connect(self, websocket: WebSocket, user_id: str):
    """
    Connect a new WebSocket client
    """
    await websocket.accept()

    # Initialize user's connections if not exists
    if user_id not in self.active_connections:
      self.active_connections[user_id] = {}
      self.user_chats[user_id] = set()

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
        if user_id in self.user_chats:
          del self.user_chats[user_id]
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

  async def broadcast_to_chat(self, message: dict, chat_id: str, skip_user_id: Optional[str] = None):
    """
    Broadcast a message to all participants in a chat
    """
    try:
      # Get chat participants from Firestore
      chat_ref = firestore_db.collection('chats').document(chat_id)
      chat = chat_ref.get()

      if not chat.exists:
        logger.error(f"Chat {chat_id} not found for broadcasting")
        return

      participants = chat.to_dict().get('participants', [])
      message_json = json.dumps(message)

      # Track users to disconnect
      disconnected = []

      # Send to all connected participants except the sender
      for participant in participants:
        if participant == skip_user_id:
          continue

        if participant in self.active_connections:
          # Add chat to user's chat set
          if participant in self.user_chats:
            self.user_chats[participant].add(chat_id)

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
      logger.error(f"Error in broadcast_to_chat: {str(e)}")

  async def handle_typing_notification(self, chat_id: str, user_id: str):
    """
    Broadcast typing notification to chat participants
    """
    typing_event = {
      'event': 'typing',
      'chatId': chat_id,
      'userId': user_id
    }
    await self.broadcast_to_chat(typing_event, chat_id, skip_user_id=user_id)

  async def handle_read_receipt(self, chat_id: str, message_id: str, user_id: str):
    """
    Broadcast read receipt to chat participants
    """
    read_event = {
      'event': 'message_read',
      'chatId': chat_id,
      'messageId': message_id,
      'userId': user_id
    }
    await self.broadcast_to_chat(read_event, chat_id, skip_user_id=user_id)

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
    Get the total number of WebSocket connections
    """
    return sum(len(connections) for connections in self.active_connections.values())