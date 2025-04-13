import logging
from typing import Annotated, Optional, List

from fastapi import Depends, HTTPException, Query
from firebase_admin import firestore
from firebase_admin.firestore import FieldFilter

from .schemas import Conversation, ConversationListResponse, ConversationType, MessagePreview
from .router import router
from ..dependencies import AuthenticatedUser, get_current_active_user
from ..firebase import firestore_db
from ..pagination import common_pagination_parameters, PaginatedResponse, PaginationParams
from ..time_utils import convert_timestamps

logger = logging.getLogger(__name__)

@router.get('/conversations', response_model=ConversationListResponse)
async def get_conversations(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(common_pagination_parameters)],
    type: Optional[str] = Query(None, description="Filter by conversation type (direct/group)"),
    unread_only: bool = Query(False, description="Filter to only show conversations with unread messages")
):
    """
    Get all conversations for the current user.
    
    - **pagination**: Page number and size parameters
    - **type**: Optional filter by conversation type ('direct' or 'group')
    - **unread_only**: Optional filter to show only conversations with unread messages
    """
    try:
        user_phone_num = current_user.phoneNumber
        
        # Query conversations where the user is a participant
        conversations_ref = firestore_db.collection('chats')
        query = conversations_ref.where(
            filter=FieldFilter('participants', 'array_contains', user_phone_num)
        ).order_by('lastMessageTime', direction='DESCENDING')
        
        # Apply type filter if specified
        if type:
            conversation_type = 'group' if type.lower() == 'group' else 'direct'
            query = query.where('type', '==', conversation_type)
        
        # Get total count for pagination
        total_docs = query.get()
        total_conversations = len(total_docs)
        
        # Apply pagination
        paginated_conversations = query.offset(
            (pagination.page - 1) * pagination.size
        ).limit(pagination.size).get()
        
        # Convert to response model
        conversations = []
        for conv in paginated_conversations:
            conv_data = conv.to_dict()
            conv_data = convert_timestamps(conv_data)
            
            # Skip if unread_only is True and this conversation has no unread messages
            if unread_only:
                # Get unread count from user_conversations subcollection
                unread_doc = firestore_db.collection('chats').document(conv.id).collection(
                    'user_stats').document(user_phone_num).get()
                
                if unread_doc.exists:
                    unread_count = unread_doc.to_dict().get('unreadCount', 0)
                    if unread_count == 0:
                        continue
                else:
                    continue
            
            # Determine conversation type
            conv_type = ConversationType.GROUP if conv_data.get('type') == 'group' else ConversationType.DIRECT
            
            # For direct chats, set the name to the other participant's name/number
            name = conv_data.get('name', '')
            if conv_type == ConversationType.DIRECT:
                participants = conv_data.get('participants', [])
                # Filter out current user to get the other participant
                other_participants = [p for p in participants if p != user_phone_num]
                if other_participants:
                    name = other_participants[0]  # Use other participant's ID as name
            
            # Get last message preview
            last_message = None
            if 'lastMessagePreview' in conv_data and 'lastMessageTime' in conv_data:
                # Try to get sender info if available
                sender_id = conv_data.get('lastMessageSenderId', '')
                
                last_message = MessagePreview(
                    content=conv_data.get('lastMessagePreview', ''),
                    sender_id=sender_id,
                    timestamp=conv_data.get('lastMessageTime'),
                    type=conv_data.get('lastMessageType', 'text')
                )
            
            # Get unread count
            unread_count = 0
            unread_doc = firestore_db.collection('chats').document(conv.id).collection(
                'user_stats').document(user_phone_num).get()
            
            if unread_doc.exists:
                unread_count = unread_doc.to_dict().get('unreadCount', 0)
            
            # Build the conversation object
            conversation = Conversation(
                id=conv.id,
                name=name,
                type=conv_type,
                last_message=last_message,
                unread_count=unread_count,
                updated_at=conv_data.get('lastMessageTime', conv_data.get('createdTime')),
                members=conv_data.get('participants', []),
                avatar_url=conv_data.get('avatarUrl'),
                is_muted=conv_data.get('mutedBy', []).count(user_phone_num) > 0
            )
            
            conversations.append(conversation)
        
        # Return paginated response
        return ConversationListResponse(
            conversations=conversations,
            has_more=(pagination.page * pagination.size) < total_conversations,
            total=total_conversations,
            page=pagination.page,
            size=pagination.size
        )
    
    except Exception as e:
        logger.error(f"Error fetching conversations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conversations")
