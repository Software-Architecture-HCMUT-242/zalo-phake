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


class ImageMetadata(BaseModel):
    """Metadata for image messages"""
    object_key: str
    url: str
    width: Optional[int] = None
    height: Optional[int] = None
    content_type: str = "image/jpeg"
    size_bytes: Optional[int] = None

class ImageUploadRequest(BaseModel):
    """Request body for getting a presigned URL for image upload"""
    content_type: str = "image/jpeg"
    filename: Optional[str] = None

class ImageUploadResponse(BaseModel):
    """Response for image upload URL request"""
    upload_url: str
    object_key: str
    file_url: str
    expires_at: str

class MessageCreate(BaseModel):
    """Request body for creating a new message"""
    content: str
    messageType: str = "text"
    metadata: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    messageId: str
    senderId: str
    content: str
    messageType: MessageType
    timestamp: datetime
    readBy: List[str]
    metadata: Optional[Dict[str, Any]] = None
    
    def get_secure_image_url(self, api_base_url: Optional[str] = None) -> Optional[str]:
        """Get the secure image URL for image messages, ensuring it goes through the auth proxy
        
        Args:
            api_base_url: Optional API base URL override
            
        Returns:
            str: Secure image URL or None if not an image message
        """
        from ..aws.config import settings
        
        if self.messageType != MessageType.IMAGE or not self.metadata:
            return None
            
        # Get image data from metadata
        object_key = self.metadata.get('object_key')
        conversation_id = self.metadata.get('conversation_id')
        
        if not object_key or not conversation_id:
            # Try to extract conversation_id from object_key if available
            if object_key and object_key.startswith('conversations/'):
                # Format: conversations/{conv_id}/images/{user_id}/{filename}
                parts = object_key.split('/')
                if len(parts) >= 2:
                    conversation_id = parts[1]
        
        if not object_key or not conversation_id:
            return None
            
        # Create secure URL through proxy
        base_url = api_base_url or settings.image_proxy_base_url
        encoded_key = object_key.replace('/', '%2F')
        return f"{base_url}/{conversation_id}/{encoded_key}"


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