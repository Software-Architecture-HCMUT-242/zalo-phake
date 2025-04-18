from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Union

from pydantic import BaseModel, Field


class NotificationType(str, Enum):
    MESSAGE = "message"
    GROUP_INVITATION = "group_invitation"
    FRIEND_REQUEST = "friend_request"
    SYSTEM = "system"


class DeliveryChannel(str, Enum):
    PUSH = "PUSH"
    IN_APP = "IN_APP"
    EMAIL = "EMAIL"


class NotificationRecipient(BaseModel):
    """Recipient information for notification events"""
    userId: str
    deliveryChannels: List[DeliveryChannel] = [DeliveryChannel.PUSH, DeliveryChannel.IN_APP]


class NotificationEvent(BaseModel):
    """Standardized notification event format to be sent to SQS"""
    eventId: str
    eventType: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    publisher: str = "chat_management"
    version: str = "1.0"
    payload: Dict[str, Any]
    recipients: List[NotificationRecipient]


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