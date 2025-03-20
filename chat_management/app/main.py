from typing import Union
import os

from fastapi import FastAPI, Query
from datetime import datetime, timezone
from functools import wraps
import jwt

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

app = FastAPI()

PATH_PREFIX = os.getenv('PATH_PREFIX', '')
API_VERSION = '/api/v1'
if not PATH_PREFIX.startswith('/'):
    PATH_PREFIX = f'/{PATH_PREFIX}'
if PATH_PREFIX.endswith('/'):
    PATH_PREFIX = PATH_PREFIX.rstrip('/')
PREFIX = f'{PATH_PREFIX}{API_VERSION}'


security = HTTPBearer()

def token_required(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        # You'll need to set up your secret key and implement proper JWT validation
        jwt.decode(token, 'your-secret-key', algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token is invalid")

@app.get(f'{PREFIX}/chats', dependencies=[Depends(token_required)])
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

@app.post(f'{PREFIX}/chats', dependencies=[Depends(token_required)])
async def create_chat(request: Request):
    data = await request.json()
    participant = data.get('participant')
    
    if not participant:
        raise HTTPException(status_code=400, detail="Participant is required")
        
    # Implementation would create chat in your database
    chat = {}  # Replace with actual chat creation
    return {'chat': chat}

@app.get(f'{PREFIX}/chats/messages', dependencies=[Depends(token_required)])
async def get_messages(limit: int = Query(None), before: str = Query(None)):
    # Implementation would fetch messages from your database
    messages = []  # Replace with actual database query
    return {'messages': messages}

@app.post(f'{PREFIX}/chats/messages', dependencies=[Depends(token_required)])
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


