from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from ..dependencies import token_required

router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.get(f'/chats/messages', )
async def get_messages(limit: int = Query(None), before: str = Query(None)):
    # Implementation would fetch messages from your database
    messages = []  # Replace with actual database query
    return {'messages': messages}

@router.post(f'/chats/messages', dependencies=[Depends(token_required)])
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