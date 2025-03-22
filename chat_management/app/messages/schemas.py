from pydantic import BaseModel
from typing import List
from datetime import datetime
from enum import Enum

class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"

class Message(BaseModel):
    messageId: str
    senderId: str
    content: str
    messageType: MessageType
    timestamp: datetime
    readBy: List[str]

