import asyncio
import json
import logging

from app.phone_utils import isVietnamesePhoneNumber
from app.service_env import Environment
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from firebase_admin import firestore

from .websocket_manager import ConnectionManager
from ..firebase import firestore_db

logger = logging.getLogger(__name__)

# Create a router for WebSocket endpoints
# Note: WebSocket routes don't use the usual APIRouter dependencies
router = APIRouter()

# Global connection manager (initialized in the module)
connection_manager = ConnectionManager()

@router.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
  """
  WebSocket endpoint for real-time messaging
  """
  # Validate phone number in development environment
  if Environment.is_dev_environment():
    if not isVietnamesePhoneNumber(user_id):
      await websocket.close(code=1008, reason="Invalid phone number")
      return

  # Establish connection
  connection_id = await connection_manager.connect(websocket, user_id)

  try:
    # Process incoming messages
    while True:
      data = await websocket.receive_text()
      try:
        message = json.loads(data)
        event_type = message.get('event')

        if event_type == 'typing':
          # User is typing in a chat
          chat_id = message.get('chatId')
          if chat_id:
            await connection_manager.handle_typing_notification(chat_id, user_id)

        elif event_type == 'message_read':
          # User has read a message
          chat_id = message.get('chatId')
          message_id = message.get('messageId')
          if chat_id and message_id:
            await connection_manager.handle_read_receipt(chat_id, message_id, user_id)

        elif event_type == 'heartbeat':
          # Update last active time for the user
          try:
            user_ref = firestore_db.collection('users').document(user_id)
            user_ref.update({
              'lastActive': firestore.SERVER_TIMESTAMP
            })
          except Exception as e:
            logger.error(f"Error updating lastActive: {str(e)}")

          # Send heartbeat acknowledgment
          await websocket.send_text(json.dumps({'event': 'heartbeat_ack'}))

      except json.JSONDecodeError:
        logger.error(f"Invalid JSON received from client: {data}")
      except Exception as e:
        logger.error(f"Error processing WebSocket message: {str(e)}")

  except WebSocketDisconnect:
    # Handle disconnection
    all_connections_closed = connection_manager.disconnect(user_id, connection_id)

    # If all user connections are closed, set offline status after grace period
    if all_connections_closed:
      asyncio.create_task(connection_manager.set_offline_status(user_id))

  except Exception as e:
    logger.error(f"WebSocket error: {str(e)}")
    # Ensure connection is removed on any error
    connection_manager.disconnect(user_id, connection_id)

# Export the connection manager so it can be used by other modules
def get_connection_manager():
  return connection_manager