from datetime import datetime
from typing import List

from pydantic import BaseModel


class Chat(BaseModel):
    chatId: str
    lastMessageTime: datetime
    lastMessagePreview: str
    participants: List[str]  # Suggested property to include participants in the chat

class GroupChat(Chat):
    name: str
    description: str
    admins: List[str]
    groupCreatedTime: datetime
    groupMembers: List[str]

class CreateChatRequest(BaseModel):
    participants: List[str]
    initialMessage: str

class CreateChatResponse(BaseModel):
    chatId: str
    createdTime: datetime