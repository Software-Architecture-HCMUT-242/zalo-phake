"""
Image proxy service for secure access to S3 images

This service ensures that only authorized users (conversation participants)
can access images stored in S3.
"""
import logging
import asyncio
import hashlib
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse, StreamingResponse
from typing import Annotated, Optional

from ..dependencies import decode_token, AuthenticatedUser, get_current_active_user
from ..firebase import firestore_db
from .s3_client import S3Client
from .config import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/images",
    dependencies=[Depends(decode_token)],
    tags=["Images"]
)

s3_client = S3Client()

@router.get("/{conversation_id}/{object_key:path}")
async def get_image(
    conversation_id: str,
    object_key: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Proxy endpoint to securely access images from S3.
    Only conversation participants can access the images.
    
    Args:
        conversation_id: The ID of the conversation the image belongs to
        object_key: The S3 object key for the image
        current_user: The authenticated user making the request
        
    Returns:
        StreamingResponse: The image data
        
    Raises:
        403: If the user is not a participant in the conversation
        404: If the image or conversation doesn't exist
    """
    user_id = current_user.phoneNumber
    
    # Validate that the user is a participant in the conversation
    try:
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = await asyncio.to_thread(conversation_ref.get)

        if not conversation.exists:
            logger.warning(f"User {user_id} attempted to access image in non-existent conversation {conversation_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation_data = conversation.to_dict()
        if user_id not in conversation_data.get('participants', []):
            logger.warning(f"Unauthorized access attempt by user {user_id} for image in conversation {conversation_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied - You are not a participant in this conversation"
            )
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error validating conversation access: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify access permissions"
        )
    
    # Validate that the image exists
    try:
        # Verify object exists and get metadata
        metadata = await asyncio.to_thread(s3_client.get_object_metadata, object_key)
        if not metadata:
            logger.warning(f"User {user_id} attempted to access non-existent image: {object_key}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found"
            )
            
        # Get media file conversation ID from object metadata or path
        media_conversation_id = metadata.get('metadata', {}).get('conversation-id')
        
        # If metadata doesn't have conversation ID, extract it from the path
        if not media_conversation_id and object_key.startswith(f"conversations/"):
            # Format is: conversations/{conv_id}/{media_type}/{user_id}/{filename}
            path_parts = object_key.split('/')
            if len(path_parts) >= 2:
                media_conversation_id = path_parts[1]
        
        # Double-check that the media file belongs to this conversation
        if media_conversation_id and media_conversation_id != conversation_id:
            logger.warning(f"User {user_id} attempted to access media from wrong conversation")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied - Media file does not belong to this conversation"
            )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error verifying media file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify media file"
        )
    
    # Generate a temporary signed URL and redirect the user
    try:
        expiration = getattr(settings, 'media_url_expiration', settings.image_url_expiration)
        signed_url = s3_client.generate_signed_url(
            object_key=object_key,
            conversation_id=conversation_id,
            user_id=user_id,
            expiration=expiration
        )
        
        # Log access for audit purposes
        logger.info(f"User {user_id} granted access to media file {object_key} in conversation {conversation_id}")
        
        # Return a redirect to the signed URL
        return RedirectResponse(url=signed_url)
        
    except Exception as e:
        logger.error(f"Error generating signed URL: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate media access URL"
        )
