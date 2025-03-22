from fastapi import APIRouter, Depends, HTTPException, Request
from ..dependencies import token_required
from ..mock import random_chat
import random
from typing import List
from .schemas import Chat
from fastapi_pagination import Page, add_pagination, paginate
router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.get(f'/chats', response_model=Page[Chat])
async def get_chats():
    # Mock data for testing
    chats = [random_chat() for _ in range(random.randint(50, 200))]
    return paginate(chats)


@router.post(f'/chats',)
async def create_chat(request: Request):
    data = await request.json()
    participant = data.get('participant')
    
    if not participant:
        raise HTTPException(status_code=400, detail="Participant is required")
        
    # Implementation would create chat in your database
    chat = {}  # Replace with actual chat creation
    return {'chat': chat}