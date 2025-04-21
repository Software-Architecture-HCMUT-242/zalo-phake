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


class ConversationDetail(BaseModel):
    """Detailed conversation model for single conversation response"""
    id: str
    name: Optional[str] = None
    type: ConversationType
    description: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    participants: List[str] = []
    admins: List[str] = []
    last_message: Optional[MessagePreview] = None
    unread_count: int = 0
    avatar_url: Optional[str] = None
    is_muted: bool = False
    metadata: Dict[str, Any] = {}


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


class ConversationMetadataUpdate(BaseModel):
    """Request model for updating conversation metadata"""
    name: Optional[str] = None
    description: Optional[str] = None
    avatar_url: Optional[str] = None


class AddMemberRequest(BaseModel):
    """Request model for adding a member to a conversation"""
    user_id: str


from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"  # Generic file type for other documents


class MessageCreate(BaseModel):
    """Request body for creating a new message"""
    content: str
    messageType: str = "text"
    

class FileInfo(BaseModel):
    """File metadata for file messages"""
    filename: str
    size: int
    mime_type: str
    s3_key: str  # S3 object key
    

class FileMessageCreate(BaseModel):
    """Request body for creating a new file message"""
    messageType: str  # One of "image", "video", "audio", or "file"
    filename: str
    description: Optional[str] = None


class Message(BaseModel):
    messageId: str
    senderId: str
    content: str
    messageType: MessageType
    timestamp: datetime
    readBy: List[str]
    file_info: Optional[FileInfo] = None  # Present only for file-based messages


# Define response models for maintenance endpoints
class ConversationUnreadDetail(BaseModel):
    conversation_id: str
    old_count: int
    new_count: int
    fixed: bool = Field(default=False, description="Whether the unread count was fixed")

class RecomputeUnreadResponse(BaseModel):
    status: str = Field(description="Status of the operation")
    processed_conversations: int = Field(description="Number of conversations processed")
    fixed_counts: int = Field(description="Number of conversations where unread counts were fixed")
    details: List[ConversationUnreadDetail] = Field(default=[], description="Details for each conversation processed")

class UnreadInconsistency(BaseModel):
    conversation_id: str
    user_id: str
    type: str = Field(description="Type of inconsistency: 'missing_user_stats' or 'count_mismatch'")
    stored_count: Optional[int] = Field(default=None, description="Current stored unread count")
    actual_count: Optional[int] = Field(default=None, description="Actual unread count from message data")

class RepairDetail(BaseModel):
    conversation_id: str
    user_id: str
    old_count: Optional[int] = Field(default=None, description="Previous unread count")
    new_count: int = Field(description="Updated unread count")
    type: str = Field(description="Type of inconsistency that was fixed")

class RepairUnreadResponse(BaseModel):
    status: str = Field(description="Status of the operation")
    total_inconsistencies: int = Field(description="Total number of inconsistencies found")
    fixed_count: int = Field(description="Number of inconsistencies fixed")
    details: List[RepairDetail] = Field(default=[], description="Details of each fixed inconsistency")