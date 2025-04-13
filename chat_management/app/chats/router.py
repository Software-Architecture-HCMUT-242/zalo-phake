import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from firebase_admin import firestore
from firebase_admin.firestore import FieldFilter

from .schemas import Chat, CreateChatRequest, CreateChatResponse  # Import CreateChatRequest
from ..dependencies import AuthenticatedUser, get_current_active_user, token_required
from ..firebase import firestore_db
from ..pagination import common_pagination_parameters, PaginatedResponse, PaginationParams
from ..time_utils import convert_timestamps

logger = logging.getLogger(__name__)


router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.get(f'/chats', response_model=PaginatedResponse[Chat])
async def get_chats(current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)], pagination: Annotated[PaginationParams, Depends(common_pagination_parameters)]):
    # Get user_id from the request context (assuming it's set during token validation)
    user_phone_num = current_user.phoneNumber
    
    # Query chats where the user is a participant
    chats_ref = firestore_db.collection('conversations')
    query = chats_ref.where(filter=FieldFilter('participants', 'array_contains', user_phone_num)).order_by('lastMessageTime', direction='DESCENDING')
    
    # Get total count for pagination
    total_docs = query.get()
    total_chats = len(total_docs)
    
    # Apply pagination
    paginated_chats = query.offset((pagination.page - 1) * pagination.size).limit(pagination.size).get()

    chats = [
        Chat(
            chatId=chat.id,
            lastMessageTime=chat.to_dict().get('lastMessageTime'),
            lastMessagePreview=chat.to_dict().get('lastMessagePreview'),
            participants=chat.to_dict().get('participants', [])
        )
        for chat in paginated_chats
    ]

    return PaginatedResponse.create(
        items=chats,
        total=total_chats,
        page=pagination.page,
        size=pagination.size
    )

@router.post(f'/chats', response_model=CreateChatResponse)
async def create_chat(request: Request, body: CreateChatRequest):
    logger.debug(f"Request body: {body}")
    # Validate participants
    if not body.participants or len(body.participants) < 2:
        raise HTTPException(status_code=400, detail="At least two participants are required")
    # Validate participants
    # if user_id not in body.participants:
    #     raise HTTPException(status_code=400, detail="Current user must be a participant")
    
    # TODO: check if user exist
    # for participant_id in body.participants:
    #     user_doc = db.collection('users').document(participant_id).get()
    #     if not user_doc.exists:
    #         raise HTTPException(status_code=404, detail=f"User {participant_id} not found")
    
    sorted_participants = sorted(body.participants)
    
    # Check if chat already exists between these participants
    chats_ref = firestore_db.collection('conversations')
    query = chats_ref.where('participants', '==', sorted_participants)
    existing_chats = list(query.stream())
    
    if existing_chats:
        # Return existing chat
        existing_chat = existing_chats[0]
        existing_data = existing_chat.to_dict()
        existing_data = convert_timestamps(existing_data)
        return CreateChatResponse(chatId=existing_chat.id, createdTime=existing_data['createdTime'])
    
    # Create chat
    chat_id = str(uuid.uuid4())
    now = firestore.SERVER_TIMESTAMP
    print(f'now: {now}')
    chat_data = {
        "lastMessageTime": now,
        "lastMessagePreview": body.initialMessage,
        "participants": sorted_participants,
        "createdTime": now,
    }
    
    # Store chat in Firestore
    chat_ref = firestore_db.collection('conversations').document(chat_id)
    chat_ref.set(chat_data)
    
    chat = chat_ref.get().to_dict()
    
    # Return created chat
    return CreateChatResponse(
        chatId=chat_id,
        createdTime=chat['createdTime'],
    )

