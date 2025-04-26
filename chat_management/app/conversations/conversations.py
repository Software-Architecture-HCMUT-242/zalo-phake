import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter
from fastapi import Depends, HTTPException, Query
from firebase_admin import firestore
from firebase_admin.firestore import FieldFilter
import traceback

from .schemas import Conversation, ConversationType, MessagePreview, ConversationResponse, \
    ConversationCreate, ConversationDetail, ConversationMetadataUpdate
from ..aws.sqs_utils import is_sqs_available, send_to_sqs
from ..dependencies import AuthenticatedUser, get_current_active_user, verify_conversation_participant
from ..dependencies import decode_token
from ..firebase import firestore_db
from ..pagination import common_pagination_parameters, PaginationParams, PaginatedResponse
from ..time_utils import convert_timestamps
from ..users.users_db import get_user_info
from ..phone_utils import is_phone_number, format_phone_number

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(decode_token)],
)
tags = ["Conversations"]

def get_conversation_metadata(conversation_data, user_phone_num):
    """
    Helper function to get the conversation name based on the type and participants.
    """
    match conversation_data.get('type'):
        case 'group':
            return conversation_data.get('name', ''), conversation_data.get('avatar_url', '')
        case 'direct':
            participants = conversation_data.get('participants', [])
            # Filter out current user to get the other participant
            other_participants = [p for p in participants if p != user_phone_num]
            name = conversation_data.get('name', '')
            avatar_url = conversation_data.get('avatar_url', '')
            if not name:
                name = other_participants[0] # Fallback to ID if no name is found
                other_participant_info = get_user_info(other_participants[0])
                if other_participant_info:
                    other_participant_name = other_participant_info.get('name', '')
                    avatar_url = other_participant_info.get('profile_pic', '')
                    if other_participant_name:
                        return other_participant_name, avatar_url  # Use other participant's ID as name

            return name, avatar_url
        case _:
            logger.warning(f"Unknown conversation type: {conversation_data.get('type')}")
            return '', ''  # Default case, should not happen if type is validated before


@router.get('/conversations', response_model=PaginatedResponse[Conversation], tags=tags)
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
        conversations_ref = firestore_db.collection('conversations')
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
                unread_doc = firestore_db.collection('conversations').document(conv.id).collection(
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
            name, avatar_url = get_conversation_metadata(conv_data, user_phone_num)

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
            unread_doc = firestore_db.collection('conversations').document(conv.id).collection(
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
                avatar_url=avatar_url,
                profile_pic=avatar_url,
                is_muted=conv_data.get('mutedBy', []).count(user_phone_num) > 0
            )

            conversations.append(conversation)

        # Return paginated response
        return PaginatedResponse.create(
            items=conversations,
            total=total_conversations,
            page=pagination.page,
            size=pagination.size
        )

    except Exception as e:
        logger.error(f"Error fetching conversations: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Failed to retrieve conversations")


@router.post('/conversations', response_model=ConversationResponse, tags=tags)
async def create_conversation(
        body: ConversationCreate,
        current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Create a new conversation (direct or group).

    For direct conversations, exactly 2 participants are required.
    For group conversations, at least 2 participants are required, and a name must be provided.

    Returns the newly created conversation or the existing one if a direct conversation
    between the same participants already exists.
    """
    logger.debug(f"Create conversation request: {body}")
    user_id = current_user.phoneNumber

    # Validate participants
    if not body.participants:
        raise HTTPException(status_code=400, detail="At least one participant is required")

    # Ensure current user is in the participants list
    if user_id not in body.participants:
        body.participants.append(user_id)

    # For direct conversations, exactly 2 participants are required
    if body.type == ConversationType.DIRECT and len(body.participants) != 2:
        raise HTTPException(status_code=400, detail="Direct conversations must have exactly 2 participants")

    # For group conversations, a name is required
    if body.type == ConversationType.GROUP and not body.name:
        raise HTTPException(status_code=400, detail="Group conversations must have a name")

    # For group conversations, at least 2 participants are required
    if body.type == ConversationType.GROUP and len(body.participants) < 2:
        raise HTTPException(status_code=400, detail="Group conversations must have at least 2 participants")

    for participant in body.participants:
        if not is_phone_number(participant):
            raise HTTPException(status_code=400, detail=f"Invalid phone number format: {participant}")

    # Sort participants for direct conversations to ensure consistency
    if body.type == ConversationType.DIRECT:
        sorted_participants = [format_phone_number(p) for p in sorted(body.participants)]

        # Check if a direct conversation already exists between these participants
        conversations_ref = firestore_db.collection('conversations')
        query = conversations_ref.where('type', '==', 'direct').where('participants', '==', sorted_participants)
        existing_conversations = list(query.stream())

        if existing_conversations:
            # Return existing conversation
            existing_conv = existing_conversations[0]
            existing_data = existing_conv.to_dict()
            existing_data = convert_timestamps(existing_data)

            # Create the last message preview if available
            last_message = None
            if 'lastMessagePreview' in existing_data and 'lastMessageTime' in existing_data:
                last_message = MessagePreview(
                    content=existing_data.get('lastMessagePreview', ''),
                    sender_id=existing_data.get('lastMessageSenderId', ''),
                    timestamp=existing_data.get('lastMessageTime'),
                    type=existing_data.get('lastMessageType', 'text')
                )

            return ConversationResponse(
                id=existing_conv.id,
                type=ConversationType.DIRECT,
                participants=existing_data.get('participants', []),
                created_at=existing_data.get('createdTime'),
                updated_at=existing_data.get('lastMessageTime', existing_data.get('createdTime')),
                last_message=last_message
            )
    else:
        # For group conversations, use the provided order
        sorted_participants = body.participants

    # Create a new conversation
    conversation_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    server_timestamp = firestore.SERVER_TIMESTAMP

    conversation_data = {
        "type": body.type.value,
        "participants": sorted_participants,
        "createdTime": server_timestamp,
        "lastMessageTime": server_timestamp,
        "metadata": body.metadata or {},
    }

    # Add name for group conversations
    if body.type == ConversationType.GROUP:
        conversation_data["name"] = body.name
        conversation_data["admins"] = [user_id]  # Creator is the initial admin

    # Add initial message if provided
    if body.initial_message:
        message_id = str(uuid.uuid4())
        conversation_data["lastMessagePreview"] = body.initial_message
        conversation_data["lastMessageType"] = "text"
        conversation_data["lastMessageSenderId"] = user_id

        # Create the message in the messages subcollection
        message_data = {
            "content": body.initial_message,
            "senderId": user_id,
            "timestamp": server_timestamp,
            "type": "text",
            "readBy": [user_id]  # Creator has read their own message
        }

    try:
        # Store conversation in Firestore
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation_ref.set(conversation_data)

        # Add initial message if provided
        if body.initial_message:
            message_ref = conversation_ref.collection('messages').document(message_id)
            message_ref.set(message_data)

            # Create user stats documents for all participants
            for participant in sorted_participants:
                unread_count = 0 if participant == user_id else 1
                user_stats = {
                    "unreadCount": unread_count,
                    "lastReadMessageId": message_id if participant == user_id else None
                }
                user_stats_ref = conversation_ref.collection('user_stats').document(participant)
                user_stats_ref.set(user_stats)
    except Exception as e:
        logger.error(f"Error creating conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create conversation")

    # Get the created conversation
    conversation = conversation_ref.get().to_dict()
    conversation = convert_timestamps(conversation)

    # Send notifications to participants (except the creator)
    if body.type == ConversationType.GROUP:
        event_type = "group_conversation_created"
    else:
        event_type = "direct_conversation_created"

    # Prepare notification payload
    notification_payload = {
        "conversation_id": conversation_id,
        "creator_id": user_id,
        "type": body.type.value,
        "participants": sorted_participants,
        "name": body.name if body.type == ConversationType.GROUP else None,
        "initial_message": body.initial_message,
        "timestamp": now.isoformat()
    }

    # Send notification via SQS if available
    if is_sqs_available():
        try:
            await send_to_sqs(event_type, notification_payload)
            logger.info(f"Sent {event_type} notification for conversation {conversation_id}")
        except Exception as e:
            logger.error(f"Failed to send notification: {str(e)}")

    # Create the last message preview if available
    last_message = None
    if body.initial_message:
        last_message = MessagePreview(
            content=body.initial_message,
            sender_id=user_id,
            timestamp=now,
            type="text",
            id=message_id
        )

    # Return the created conversation
    return ConversationResponse(
        id=conversation_id,
        type=body.type,
        name=body.name if body.type == ConversationType.GROUP else None,
        participants=sorted_participants,
        created_at=now,
        updated_at=now,
        last_message=last_message
    )


@router.get('/conversations/{conversation_id}',
            response_model=ConversationDetail,
            tags=tags,
            dependencies=[Depends(verify_conversation_participant)])
async def get_conversation(
    conversation_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Get details of a specific conversation (direct or group).
    
    Only members of the conversation can access its details.
    
    Returns:
        The conversation details including participants, messages, and metadata.
    
    Raises:
        404: If the conversation is not found
        403: If the user is not a member of the conversation
        500: If there's a server error
    """
    try:
        user_phone_num = current_user.phoneNumber
        
        # Get the conversation from Firestore
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = conversation_ref.get()
        
        # Convert to dict and handle timestamps
        conversation_data = conversation.to_dict()
        conversation_data = convert_timestamps(conversation_data)

        # Determine conversation type
        conv_type = ConversationType.GROUP if conversation_data.get('type') == 'group' else ConversationType.DIRECT
        
        # For direct chats, set the name to the other participant's name/number
        name = conversation_data.get('name', '')
        if conv_type == ConversationType.DIRECT:
            participants = conversation_data.get('participants', [])
            # Filter out current user to get the other participant
            other_participants = [p for p in participants if p != user_phone_num]
            if other_participants:
                name = other_participants[0]  # Use other participant's ID as name
        
        # Get last message preview
        last_message = None
        if 'lastMessagePreview' in conversation_data and 'lastMessageTime' in conversation_data:
            # Try to get sender info if available
            sender_id = conversation_data.get('lastMessageSenderId', '')
            
            last_message = MessagePreview(
                content=conversation_data.get('lastMessagePreview', ''),
                sender_id=sender_id,
                timestamp=conversation_data.get('lastMessageTime'),
                type=conversation_data.get('lastMessageType', 'text')
            )
        
        # Get unread count for the current user
        unread_count = 0
        unread_doc = conversation_ref.collection('user_stats').document(user_phone_num).get()
        
        if unread_doc.exists:
            unread_count = unread_doc.to_dict().get('unreadCount', 0)
        
        # Get additional metadata for group conversations
        description = ''
        admins = []
        if conv_type == ConversationType.GROUP:
            description = conversation_data.get('description', '')
            admins = conversation_data.get('admins', [])
        
        # Check if the conversation is muted for the current user
        is_muted = user_phone_num in conversation_data.get('mutedBy', [])
        
        # Build the detailed conversation object
        detailed_conversation = ConversationDetail(
            id=conversation_id,
            name=name,
            type=conv_type,
            description=description,
            created_at=conversation_data.get('createdTime'),
            updated_at=conversation_data.get('lastMessageTime', conversation_data.get('createdTime')),
            participants=conversation_data.get('participants', []),
            admins=admins,
            last_message=last_message,
            unread_count=unread_count,
            avatar_url=conversation_data.get('avatarUrl'),
            is_muted=is_muted,
            metadata=conversation_data.get('metadata', {})
        )
        
        return detailed_conversation
        
    except HTTPException as e:
        # Re-raise HTTP exceptions to maintain their status codes and details
        raise
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to retrieve conversation details")


@router.put('/conversations/{conversation_id}',
            response_model=ConversationDetail,
            tags=tags,
            dependencies=[Depends(verify_conversation_participant)]
            )
async def update_conversation_metadata(
    conversation_id: str,
    body: ConversationMetadataUpdate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Update metadata for a group conversation (name, description, avatar_url).
    Only admins can update group conversation metadata.
    This operation is only applicable for conversations with type 'group'.
    
    Returns the updated conversation details.
    
    Raises:
        401: If authentication is invalid
        403: If the user is not an admin or if the conversation is not a group
        404: If the conversation is not found
        500: If there's a server error
    """
    try:
        user_phone_num = current_user.phoneNumber
        
        # Get the conversation from Firestore
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        conversation = conversation_ref.get()
        

        # Convert to dict and handle timestamps
        conversation_data = conversation.to_dict()
        
        # Check if the conversation is a group
        if conversation_data.get('type') != 'group':
            raise HTTPException(status_code=403, detail="This operation is only applicable for group conversations")
        
        # Check if the user is an admin
        if user_phone_num not in conversation_data.get('admins', []):
            raise HTTPException(status_code=403, detail="Only admins can update group metadata")
        
        # Prepare update data with only the fields that need changing
        update_data = {}
        
        if body.name is not None:
            update_data['name'] = body.name
            
        if body.description is not None:
            update_data['description'] = body.description
            
        if body.avatar_url is not None:
            update_data['avatarUrl'] = body.avatar_url
        
        # Only update if there's something to update
        if update_data:
            # Update lastMessageTime to track the modification
            update_data['lastMessageTime'] = firestore.SERVER_TIMESTAMP
            
            # Update the conversation
            conversation_ref.update(update_data)
        
        # Get the updated conversation
        updated_conversation = conversation_ref.get()
        updated_data = updated_conversation.to_dict()
        updated_data = convert_timestamps(updated_data)
        
        # Build and return the detailed conversation object
        return ConversationDetail(
            id=conversation_id,
            name=updated_data.get('name'),
            type=ConversationType.GROUP,
            description=updated_data.get('description', ''),
            created_at=updated_data.get('createdTime'),
            updated_at=updated_data.get('lastMessageTime', updated_data.get('createdTime')),
            participants=updated_data.get('participants', []),
            admins=updated_data.get('admins', []),
            last_message=MessagePreview(
                content=updated_data.get('lastMessagePreview', ''),
                sender_id=updated_data.get('lastMessageSenderId', ''),
                timestamp=updated_data.get('lastMessageTime'),
                type=updated_data.get('lastMessageType', 'text')
            ) if 'lastMessagePreview' in updated_data and 'lastMessageTime' in updated_data else None,
            unread_count=0,  # We don't need to calculate this for the updating user
            avatar_url=updated_data.get('avatarUrl'),
            is_muted=user_phone_num in updated_data.get('mutedBy', []),
            metadata=updated_data.get('metadata', {})
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error updating conversation {conversation_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update conversation metadata")
