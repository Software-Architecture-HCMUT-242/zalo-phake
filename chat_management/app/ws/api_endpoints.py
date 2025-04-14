import asyncio
import json
import logging
import os
import socket
import time

from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field

from .router import get_connection_manager, is_conversation_participant
from ..aws.elasticache import chat_management_client
from ..dependencies import get_current_active_user
from ..firebase import firestore_db

logger = logging.getLogger(__name__)

router = APIRouter()

# Request validation models
class StatusUpdate(BaseModel):
    """Request model for status updates"""
    status: str = Field(..., description="User status value (e.g. 'available', 'away', 'busy', 'offline')")

class MessageRead(BaseModel):
    """Request model for marking messages as read"""
    conversation_id: str = Field(..., description="ID of the conversation containing the message")
    message_id: str = Field(..., description="ID of the message being marked as read")
    
class TypingNotification(BaseModel):
    """Request model for typing notifications"""
    conversation_id: str = Field(..., description="ID of the conversation where typing is occurring")


@router.post("/api/user/status", status_code=status.HTTP_200_OK)
async def update_user_status(status_data: StatusUpdate, current_user = Depends(get_current_active_user)):
    """
    Update a user's status and broadcast to relevant conversations
    
    Args:
        status_data: Object containing the new status value
        current_user: The authenticated user (from dependency)
    
    Returns:
        Success message with the updated status
    
    Raises:
        HTTPException: If request is invalid or if an error occurs during processing
    """
    user_id = current_user.phoneNumber
    status_value = status_data.status
    
    # Validate status value
    valid_statuses = ['available', 'away', 'busy', 'invisible', 'offline']
    if status_value not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status value. Must be one of: {', '.join(valid_statuses)}"
        )
    
    try:
        # Get the connection manager
        connection_manager = get_connection_manager()
        
        # Update user status in database and broadcast to other users
        await connection_manager.handle_user_activity(
            user_id=user_id,
            activity_type='status_change',
            metadata={'status': status_value}
        )
        
        return {"message": f"Status updated to '{status_value}'"}
    
    except Exception as e:
        logger.error(f"Error updating user status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update status. Please try again."
        )


@router.post("/api/messages/read", status_code=status.HTTP_200_OK)
async def mark_message_read(read_data: MessageRead, current_user = Depends(get_current_active_user)):
    """
    Mark a message as read by the current user
    
    Args:
        read_data: Object containing conversation_id and message_id
        current_user: The authenticated user (from dependency)
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If request is invalid or if an error occurs during processing
    """
    user_id = current_user.phoneNumber
    conversation_id = read_data.conversation_id
    message_id = read_data.message_id

    # Verify user is a participant in the conversation
    if not await is_conversation_participant(conversation_id, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a participant in this conversation"
        )
    
    try:
        # Get the connection manager
        connection_manager = get_connection_manager()
        
        # Update read status and broadcast to other participants
        await connection_manager.handle_read_receipt(conversation_id, message_id, user_id)
        return {"message": "Message marked as read"}
    
    except Exception as e:
        logger.error(f"Error marking message as read: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mark message as read. Please try again."
        )


@router.post("/api/conversations/{conversation_id}/typing", status_code=status.HTTP_200_OK)
async def send_typing_notification(conversation_id: str, current_user = Depends(get_current_active_user)):
    """
    Send a typing notification to a conversation
    
    Args:
        conversation_id: ID of the conversation where typing is occurring
        current_user: The authenticated user (from dependency)
    
    Returns:
        Success message
    
    Raises:
        HTTPException: If request is invalid or if an error occurs during processing
    """
    user_id = current_user.phoneNumber
    
    # Verify conversation exists
    conversation_ref = firestore_db.collection('conversations').document(conversation_id)
    conversation = await asyncio.to_thread(conversation_ref.get)
    
    if not conversation.exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found"
        )
    
    # Verify user is a participant
    participants = conversation.to_dict().get('participants', [])
    if user_id not in participants:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a participant in this conversation"
        )
    
    try:
        # Get the connection manager
        connection_manager = get_connection_manager()
        
        # Send typing notification
        await connection_manager.handle_typing_notification(conversation_id, user_id)
        return {"message": "Typing notification sent"}
    
    except Exception as e:
        logger.error(f"Error sending typing notification: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send typing notification. Please try again."
        )


@router.get("/api/connections/info", status_code=status.HTTP_200_OK)
async def get_connection_info(current_user = Depends(get_current_active_user)):
    """
    Get information about the current user's WebSocket connections
    
    Args:
        current_user: The authenticated user (from dependency)
    
    Returns:
        Connection information including count and status
    
    Raises:
        HTTPException: If an error occurs during processing
    """
    user_id = current_user.phoneNumber
    
    try:
        # Get connection data from chat_management service
        all_connections = await chat_management_client.get_user_connections(user_id)
        
        # Parse connection data
        connections_by_instance = {}
        for conn_info in all_connections:
            instance_id = conn_info.get('instance_id', 'unknown')
            connection_id = conn_info.get('connection_id')
            metadata = conn_info.get('metadata', {})
            
            if instance_id not in connections_by_instance:
                connections_by_instance[instance_id] = []
                
            connections_by_instance[instance_id].append({
                "connection_id": connection_id,
                "created_at": metadata.get('connected_at'),
                "ip_address": metadata.get('ip_address', 'unknown')
            })
        
        # Get user status from Firestore
        user_ref = firestore_db.collection('users').document(user_id)
        user_data = await asyncio.to_thread(user_ref.get)
        user_status = user_data.to_dict().get('status', 'offline') if user_data.exists else 'offline'
        is_online = user_data.to_dict().get('isOnline', False) if user_data.exists else False
        last_active = user_data.to_dict().get('lastActive')
        
        return {
            "user_id": user_id,
            "is_online": is_online,
            "status": user_status,
            "last_active": last_active if last_active else None,
            "total_connections": len(all_connections),
            "connections_by_instance": connections_by_instance
        }
        
    except Exception as e:
        logger.error(f"Error retrieving connection info: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve connection information."
        )


@router.get("/api/connections/stats", status_code=status.HTTP_200_OK)
async def get_connection_stats(current_user = Depends(get_current_active_user)):
    """
    Get global statistics about WebSocket connections across all instances
    
    Args:
        current_user: The authenticated user (from dependency)
    
    Returns:
        Connection statistics for the entire system
    
    Raises:
        HTTPException: If an error occurs during processing
    """
    # Check if user is an admin (example - adjust according to your auth system)
    user_id = current_user.phoneNumber
    user_ref = firestore_db.collection('users').document(user_id)
    user_data = await asyncio.to_thread(user_ref.get)
    
    # Verify user has admin role
    if not user_data.exists or not user_data.to_dict().get('isAdmin', False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this endpoint"
        )
    
    try:
        # Get the connection manager
        connection_manager = get_connection_manager()
        
        # Get global connection statistics
        stats = await connection_manager.get_connection_stats()
        return stats
    
    except Exception as e:
        logger.error(f"Error retrieving connection statistics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve connection statistics"
        )


@router.get("/api/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Health check endpoint for load balancers and monitoring
    
    Returns:
        Health status information including chat_management service and Firestore connectivity
    
    Raises:
        HTTPException: If critical services are unavailable
    """
    # Get the connection manager
    connection_manager = get_connection_manager()
    
    health_status = {
        "status": "healthy",
        "instance_id": os.environ.get("INSTANCE_ID", socket.gethostname()),
        "timestamp": time.time(),
        "services": {}
    }
    
    # Check chat_management service connectivity
    try:
        is_connected = chat_management_client.is_connected()
        if is_connected:
            health_status["services"]["chat_management"] = {
                "status": "connected",
                "message": "Chat management service connection successful"
            }
        else:
            health_status["services"]["chat_management"] = {
                "status": "error",
                "message": "Chat management service not connected"
            }
            health_status["status"] = "degraded"
    except Exception as e:
        logger.error(f"Chat management service health check failed: {str(e)}")
        health_status["services"]["chat_management"] = {
            "status": "error",
            "message": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check Firestore connectivity
    try:
        # Using a lightweight read operation for health check
        system_ref = firestore_db.collection('system').document('health')
        await asyncio.to_thread(system_ref.get)
        health_status["services"]["firestore"] = {
            "status": "connected",
            "message": "Firestore connection successful"
        }
    except Exception as e:
        logger.error(f"Firestore health check failed: {str(e)}")
        health_status["services"]["firestore"] = {
            "status": "error",
            "message": str(e)
        }
        health_status["status"] = "degraded"
    
    # Add WebSocket connection statistics
    health_status["connections"] = {
        "active_users": len(connection_manager.active_connections),
        "total_connections": connection_manager.get_total_connections_count()
    }
    
    # If all critical services are down, return 503
    if all(service["status"] == "error" for service in health_status["services"].values()):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="All critical services are unavailable"
        )
    
    return health_status
