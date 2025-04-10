from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ..dependencies import token_required
from ..mock import random_message
import random
# import all you need from fastapi-pagination
from fastapi_pagination import Page, add_pagination, paginate
from .schemas import Message
from ..firebase import realtime_db, firestore_db, firebase_db
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.get('/chats/{chat_id}/messages', response_model=Page[Message])
async def get_messages(chat_id: str):
    pass

@router.post(f'/chats/messages', )
async def send_message(request: Request):
    data = await request.json()
    content = data.get('content')
    
    if not content:
        raise HTTPException(status_code=400, detail="Content is required")
        
    # Implementation would save message to your database
    message = {
        'content': content,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        # Add other message properties
    }
    return {'message': message}, 201