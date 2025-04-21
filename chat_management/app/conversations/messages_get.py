import asyncio
import json
import logging
import os
import socket
import traceback
import uuid
from datetime import datetime, timezone
from typing import Annotated, List

from fastapi import APIRouter, Depends, HTTPException, status
from firebase_admin import firestore
from google.cloud.firestore_v1.base_query import BaseQuery

from .schemas import Message, MessageType, MessageCreate
from ..aws.sqs_utils import is_sqs_available
from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user, verify_conversation_participant
from ..firebase import firestore_db
from ..notifications.service import NotificationService
from ..pagination import PaginatedResponse, PaginationParams, common_pagination_parameters
from ..redis.connection import get_redis_connection
from ..time_utils import convert_timestamps
from ..ws.router import get_connection_manager

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(decode_token)],
)

notification_service = NotificationService()
connection_manager = get_connection_manager()
tags = ["Messages"]


@router.get('/conversations/{conversation_id}/messages',
            response_model=PaginatedResponse[Message],
            tags=tags,
            dependencies=[Depends(verify_conversation_participant)])
async def get_conversation_messages(
        conversation_id: str,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
        pagination: Annotated[PaginationParams, Depends(common_pagination_parameters)]
):
    """
    Get paginated messages for a specific conversation
    
    Args:
        conversation_id: The ID of the conversation to retrieve messages from
        current_user: The authenticated user making the request
        pagination: Pagination parameters (page, size)
        
    Returns:
        PaginatedResponse: A paginated list of messages
        
    Raises:
        404: If the conversation doesn't exist
        403: If the user is not a participant in the conversation
    """
    # Query messages for this conversation
    messages_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages')
    query = messages_ref.order_by('timestamp', direction=BaseQuery.DESCENDING)

    # Get total count for pagination
    try:
        total_docs = await asyncio.to_thread(query.get)
        total_messages = len(total_docs)
    except Exception as e:
        logger.error(f"Error fetching message count: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to retrieve messages"
        )

    # Apply pagination
    try:
        offset = (pagination.page - 1) * pagination.size
        paginated_msgs = await asyncio.to_thread(query.offset(offset).limit(pagination.size).get)
    except Exception as e:
        logger.error(f"Error applying pagination: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Failed to retrieve messages"
        )

    # Transform messages to the response model
    messages = []
    for msg in paginated_msgs:
        try:
            msg_data = msg.to_dict()
            # Convert Firestore timestamps to datetime objects
            msg_data = convert_timestamps(msg_data)
            # Create Message object
            messages.append(Message(
                messageId=msg.id,
                senderId=msg_data.get('senderId'),
                content=msg_data.get('content', ''),
                messageType=msg_data.get('messageType', MessageType.TEXT),
                timestamp=msg_data.get('timestamp'),
                readBy=msg_data.get('readBy', [])
            ))
        except Exception as e:
            logger.error(f"Error processing message {msg.id}: {str(e)}")
            print(traceback.format_exc())
            # Continue to next message instead of failing the entire request

    # Create the paginated response
    return PaginatedResponse.create(
        items=messages,
        total=total_messages,
        page=pagination.page,
        size=pagination.size
    )