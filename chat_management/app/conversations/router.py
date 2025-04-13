import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
import logging
from typing import Annotated, Optional

from fastapi import Depends, HTTPException, Query
from firebase_admin import firestore
from firebase_admin.firestore import FieldFilter

from .schemas import Conversation, ConversationListResponse, ConversationType, MessagePreview, ConversationResponse, \
    ConversationCreate
from ..aws.sqs_utils import is_sqs_available, send_to_sqs
from ..dependencies import AuthenticatedUser, get_current_active_user
from ..firebase import firestore_db
from ..pagination import common_pagination_parameters, PaginationParams
from ..time_utils import convert_timestamps

from ..dependencies import token_required


logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(token_required)],
)


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


@router.post('/conversations', response_model=ConversationResponse)
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

    # Sort participants for direct conversations to ensure consistency
    if body.type == ConversationType.DIRECT:
        sorted_participants = sorted(body.participants)

        # Check if a direct conversation already exists between these participants
        conversations_ref = firestore_db.collection('chats')
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
        conversation_ref = firestore_db.collection('chats').document(conversation_id)
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
