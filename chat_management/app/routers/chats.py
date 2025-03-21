from fastapi import APIRouter, Depends, HTTPException, Request
from ..dependencies import token_required

router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.get(f'/chats',)
async def get_chats():
    # Mock data for testing
    chats = [
        {
            'id': 1,
            'participant': 'user1',
            'created_at': '2023-07-20T10:00:00Z',
            'last_message': 'Hello there!'
        },
        {
            'id': 2, 
            'participant': 'user2',
            'created_at': '2023-07-20T11:00:00Z',
            'last_message': 'How are you?'
        }
    ]
    return {'chats': chats}


@router.post(f'/chats',)
async def create_chat(request: Request):
    data = await request.json()
    participant = data.get('participant')
    
    if not participant:
        raise HTTPException(status_code=400, detail="Participant is required")
        
    # Implementation would create chat in your database
    chat = {}  # Replace with actual chat creation
    return {'chat': chat}