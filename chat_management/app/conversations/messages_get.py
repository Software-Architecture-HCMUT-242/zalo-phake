import asyncio
import logging
import traceback
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud.firestore_v1.base_query import BaseQuery

from .schemas import Message, MessageType, FileInfo
from ..aws.config import settings
from ..aws.s3_utils import s3_client
from ..dependencies import decode_token, verify_conversation_participant
from ..firebase import firestore_db
from ..notifications.service import NotificationService
from ..pagination import PaginatedResponse, PaginationParams, common_pagination_parameters
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
            # Get file info if this is a file-based message
            file_info = None
            file_url = None
            message_type = msg_data.get('messageType', MessageType.TEXT)
            
            # Generate pre-signed URL for file-based messages
            if message_type in [MessageType.IMAGE, MessageType.VIDEO, MessageType.AUDIO, MessageType.FILE]:
                file_info_data = msg_data.get('file_info')
                if file_info_data:
                    file_info = FileInfo(
                        filename=file_info_data.get('filename', ''),
                        size=file_info_data.get('size', 0),
                        mime_type=file_info_data.get('mime_type', 'application/octet-stream'),
                        s3_key=file_info_data.get('s3_key', '')
                    )
                    
                    # Generate pre-signed URL if S3 client is available
                    if s3_client and file_info.s3_key:
                        try:
                            file_url = s3_client.generate_presigned_url(file_info.s3_key)
                        except Exception as e:
                            logger.error(f"Error generating presigned URL for {file_info.s3_key}: {str(e)}")
                            # Continue without URL - client can request it separately if needed
            
            # Create Message object
            messages.append(Message(
                messageId=msg.id,
                senderId=msg_data.get('senderId'),
                content=msg_data.get('content', ''),
                messageType=message_type,
                timestamp=msg_data.get('timestamp'),
                readBy=msg_data.get('readBy', []),
                file_info=file_info,
                file_url=file_url
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


@router.get('/conversations/{conversation_id}/messages/{message_id}/file',
            tags=tags,
            dependencies=[Depends(verify_conversation_participant)],
            description="Get/Refresh a presigned URL for a file attached to a message.")
async def get_message_file_url(
        conversation_id: str,
        message_id: str
):
    """
    Get/Refresh a presigned URL for a file attached to a message.
    
    Args:
        conversation_id: The ID of the conversation
        message_id: The ID of the message
        current_user: The authenticated user making the request
        
    Returns:
        dict: File info and presigned URL
        
    Raises:
        404: If the message doesn't exist or doesn't have a file
        403: If the user is not a participant in the conversation
    """
    # Check if S3 client is available
    if not s3_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File service is not available"
        )
        
    # Get the message from Firestore
    message_ref = firestore_db.collection('conversations').document(conversation_id).collection('messages').document(message_id)
    
    try:
        message = await asyncio.to_thread(message_ref.get)
        if not message.exists:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message not found"
            )
            
        message_data = message.to_dict()
        file_info_data = message_data.get('file_info')
        
        if not file_info_data or not file_info_data.get('s3_key'):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Message does not contain a file"
            )
            
        # Create the FileInfo model
        file_info = FileInfo(
            filename=file_info_data.get('filename', ''),
            size=file_info_data.get('size', 0),
            mime_type=file_info_data.get('mime_type', 'application/octet-stream'),
            s3_key=file_info_data.get('s3_key', '')
        )
        
        # Generate a new presigned URL
        file_url = s3_client.generate_presigned_url(file_info.s3_key)
        
        # Return the file info and URL
        return {
            "file_info": file_info,
            "file_url": file_url,
            "expires_in": settings.aws_s3_presigned_url_expiration
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error getting file URL for message {message_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate file URL"
        )