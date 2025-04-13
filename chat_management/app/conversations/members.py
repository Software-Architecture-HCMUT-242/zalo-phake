import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore

from .schemas import AddMemberRequest
from ..dependencies import AuthenticatedUser, get_current_active_user, token_required
from ..firebase import firestore_db

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.post('/conversations/{conversation_id}/members', status_code=200)
async def add_conversation_member(
    conversation_id: str,
    body: AddMemberRequest,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Add a new member to a group conversation.
    Only conversation admins can add members.
    """
    # Get the conversation document
    try:
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = conversation_ref.get()
        
        # Check if conversation exists
        if not conversation.exists:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        conversation_data = conversation.to_dict()
        
        # Verify this is a group conversation
        if conversation_data.get('type') != 'group':
            raise HTTPException(status_code=403, detail="This operation is only allowed for group conversations")
        
        # Verify current user is a member of the conversation
        if current_user.phoneNumber not in conversation_data.get('participants', []):
            raise HTTPException(status_code=403, detail="You are not a member of this conversation")
        
        # Verify current user is an admin of the conversation
        if current_user.phoneNumber not in conversation_data.get('admins', []):
            raise HTTPException(status_code=403, detail="Only conversation admins can add members")
        
        # Verify the new user is not already a member
        if body.user_id in conversation_data.get('participants', []):
            raise HTTPException(status_code=400, detail="User is already a member of this conversation")
        
        # Optional: Verify the user_id exists in the users collection
        user_ref = firestore_db.collection('users').document(body.user_id).get()
        if not user_ref.exists:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Add the user to the conversation participants
        conversation_ref.update({
            'participants': firestore.ArrayUnion([body.user_id]),
            'lastUpdateTime': firestore.SERVER_TIMESTAMP
        })
        
        return {"success": True}
    
    except HTTPException as e:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log any other errors and return a 500 error
        logger.error(f"Error adding member to conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="An error occurred while adding member to conversation")

