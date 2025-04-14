from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class NotificationType(str, Enum):
    MESSAGE = "message"
    GROUP_INVITATION = "group_invitation"
    FRIEND_REQUEST = "friend_request"
    SYSTEM = "system"

class NotificationData(BaseModel):
    """Data payload for notifications with conversation-related fields"""
    conversationId: Optional[str] = None
    messageId: Optional[str] = None
    senderId: Optional[str] = None
    type: Optional[str] = None

class Notification(BaseModel):
    notificationId: str
    userId: str
    type: NotificationType
    title: str
    body: str
    data: Optional[NotificationData] = None
    isRead: bool = False
    createdAt: datetime

class NotificationPreference(BaseModel):
    userId: str
    pushEnabled: bool = True
    messageNotifications: bool = True
    groupNotifications: bool = True
    friendRequestNotifications: bool = True
    systemNotifications: bool = True
    muteUntil: Optional[datetime] = None

class DeviceToken(BaseModel):
    userId: str
    token: str
    deviceType: str  # "ios", "android", "web"
    lastUpdated: datetime