import asyncio
import json
import logging
from typing import Dict, Any

from app.phone_utils import isVietnamesePhoneNumber
from app.service_env import Environment
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Depends, status
from firebase_admin import firestore

# ConnectionManager is now imported through get_connection_manager
from ..dependencies import decode_token
from ..firebase import firestore_db

logger = logging.getLogger(__name__)

# Create a router for WebSocket endpoints
# Note: WebSocket routes don't use the usual APIRouter dependencies
router = APIRouter()

# Get the connection manager from websocket_manager module
from .websocket_manager import get_connection_manager

# Get the global connection manager
connection_manager = get_connection_manager()

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
          # User is typing in a conversation
          conversation_id = message.get('conversationId')
          if conversation_id:
            await connection_manager.handle_typing_notification(conversation_id, user_id)
          # Backward compatibility
          elif 'chatId' in message:
            chat_id = message.get('chatId')
            await connection_manager.handle_typing_notification(chat_id, user_id)
            logger.warning(f"Deprecated 'chatId' field used instead of 'conversationId' in typing event")

        elif event_type == 'message_read':
          # User has read a message
          conversation_id = message.get('conversationId')
          message_id = message.get('messageId')
          if conversation_id and message_id:
            await connection_manager.handle_read_receipt(conversation_id, message_id, user_id)
          # Backward compatibility
          elif 'chatId' in message and message.get('messageId'):
            chat_id = message.get('chatId')
            message_id = message.get('messageId')
            await connection_manager.handle_read_receipt(chat_id, message_id, user_id)
            logger.warning(f"Deprecated 'chatId' field used instead of 'conversationId' in message_read event")

        elif event_type == 'heartbeat':
          # Update last active time for the user using the handle_user_activity method
          await connection_manager.handle_user_activity(
            user_id=user_id, 
            activity_type='heartbeat'
          )

          # Send heartbeat acknowledgment
          await websocket.send_text(json.dumps({'event': 'heartbeat_ack'}))
          
        elif event_type == 'status_change':
          # Handle user status change (available, away, busy, etc.)
          status = message.get('status')
          if status:
            await connection_manager.handle_user_activity(
              user_id=user_id, 
              activity_type='status_change',
              metadata={'status': status}
            )
            # Acknowledge status change
            await websocket.send_text(json.dumps({
              'event': 'status_change_ack',
              'status': status
            }))
          else:
            logger.warning(f"Missing status in status_change event from user {user_id}")
            await websocket.send_text(json.dumps({
              'event': 'error',
              'message': 'Missing status parameter'
            }))

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

# The get_connection_manager function is now imported from websocket_manager


async def is_conversation_participant(conversation_id: str, user_id: str) -> bool:
  """
  Check if a user is a participant in a given conversation
  
  Args:
      conversation_id: ID of the conversation to check
      user_id: ID of the user to check (phone number)
  
  Returns:
      bool: True if the user is a participant, False otherwise
  
  Raises:
      Exception: If there's an error accessing Firestore
  """
  try:
    # Get the conversation document from Firestore
    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = await asyncio.to_thread(conversation_ref.get)
    
    # Check if conversation exists
    if not conversation.exists:
      logger.warning(f"Conversation {conversation_id} not found when checking participation")
      return False
    
    # Get the participants list and check if user is in it
    conversation_data = conversation.to_dict()
    participants = conversation_data.get('participants', [])
    
    return user_id in participants
    
  except Exception as e:
    logger.error(f"Error checking conversation participation: {str(e)}")
    raise e


# HTTP endpoints for WebSocket-related operations
# @router.post("/user/status", status_code=status.HTTP_200_OK)
# async def update_user_status(status_data: Dict[str, Any], current_user = Depends(decode_token)):
#   """
#   Update a user's status and broadcast to relevant conversations
#
#   Args:
#       status_data: Dictionary containing 'status' field with the new status value
#       current_user: The authenticated user (from dependency)
#
#   Returns:
#       Success message
#
#   Raises:
#       HTTPException: If request is invalid or if an error occurs during processing
#   """
#   if not current_user:
#     raise HTTPException(
#       status_code=status.HTTP_401_UNAUTHORIZED,
#       detail="Authentication required"
#     )
#
#   user_id = current_user.phoneNumber
#
#   # Validate status data
#   if not status_data or 'status' not in status_data:
#     raise HTTPException(
#       status_code=status.HTTP_400_BAD_REQUEST,
#       detail="Missing required 'status' field"
#     )
#
#   status_value = status_data.get('status')
#   valid_statuses = ['available', 'away', 'busy', 'invisible', 'offline']
#
#   if status_value not in valid_statuses:
#     raise HTTPException(
#       status_code=status.HTTP_400_BAD_REQUEST,
#       detail=f"Invalid status value. Must be one of: {', '.join(valid_statuses)}"
#     )
#
#   try:
#     # Update user status in database
#     user_ref = firestore_db.collection('users').document(user_id)
#     await asyncio.to_thread(
#       user_ref.update,
#       {
#         'status': status_value,
#         'lastActive': firestore.SERVER_TIMESTAMP,
#         'lastActivityType': 'status_change'
#       }
#     )
#
#     # Broadcast status change through WebSockets
#     await connection_manager.handle_user_activity(
#       user_id=user_id,
#       activity_type='status_change',
#       metadata={'status': status_value}
#     )
#
#     return {"message": f"Status updated to '{status_value}'"}
#
#   except Exception as e:
#     logger.error(f"Error updating user status: {str(e)}")
#     raise HTTPException(
#       status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#       detail="Failed to update status. Please try again."
#     )


# @router.get("/connections/info", status_code=status.HTTP_200_OK)
# async def get_connection_info(current_user = Depends(decode_token)):
#   """
#   Get information about the current user's WebSocket connections
#
#   Args:
#       current_user: The authenticated user (from dependency)
#
#   Returns:
#       Connection information including count and status
#
#   Raises:
#       HTTPException: If request is invalid or if an error occurs during processing
#   """
#   if not current_user:
#     raise HTTPException(
#       status_code=status.HTTP_401_UNAUTHORIZED,
#       detail="Authentication required"
#     )
#
#   user_id = current_user.phoneNumber
#
#   try:
#     # Get connection counts
#     user_connection_count = connection_manager.get_user_connection_count(user_id)
#     total_users = connection_manager.get_connected_users_count()
#
#     return {
#       "user_id": user_id,
#       "active_connections": user_connection_count,
#       "is_connected": connection_manager.is_user_connected(user_id),
#       "total_connected_users": total_users
#     }
#
#   except Exception as e:
#     logger.error(f"Error retrieving connection info: {str(e)}")
#     raise HTTPException(
#       status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#       detail="Failed to retrieve connection information."
#     )