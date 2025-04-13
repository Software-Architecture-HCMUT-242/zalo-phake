from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, Field


class ConversationType(str, Enum):
    DIRECT = "direct"
    GROUP = "group"


class MessagePreview(BaseModel):
    """Preview of the last message in a conversation"""
    content: str
    sender_id: str = ""
    timestamp: Optional[datetime] = None
    type: str = "text"  # Default to text message
    id: Optional[str] = None


class Participant(BaseModel):
    """Participant in a conversation"""
    user_id: str
    nickname: Optional[str] = None
    role: Optional[str] = None  # 'admin', 'member', etc.
    joined_at: datetime


class Conversation(BaseModel):
    """Conversation model for list response"""
    id: str
    name: Optional[str] = None
    type: ConversationType
    last_message: Optional[MessagePreview] = None
    unread_count: int = 0
    updated_at: datetime
    members: List[str] = []
    avatar_url: Optional[str] = None
    is_muted: bool = False


class ConversationListResponse(BaseModel):
    """Response model for listing conversations"""
    conversations: List[Conversation]
    has_more: bool
    total: int
    page: int
    size: int


class ConversationCreate(BaseModel):
    """Request body for creating a new conversation"""
    type: ConversationType = ConversationType.DIRECT
    name: Optional[str] = None  # Required for group conversations
    participants: List[str]  # List of user phone numbers/IDs
    initial_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class ConversationResponse(BaseModel):
    """Response for a created conversation"""
    id: str
    type: ConversationType
    name: Optional[str] = None
    participants: List[str]
    created_at: datetime
    updated_at: datetime
    last_message: Optional[MessagePreview] = None


class ConversationListItem(BaseModel):
    """Conversation item in a list response"""
    id: str
    type: ConversationType
    name: Optional[str] = None
    participants: List[str]
    unread_count: int = 0
    last_message: Optional[MessagePreview] = None
    updated_at: datetime


class PaginatedConversationsResponse(BaseModel):
    """Paginated response for conversations"""
    conversations: List[ConversationListItem]
    total: int
    page: int
    size: int
    pages: int
