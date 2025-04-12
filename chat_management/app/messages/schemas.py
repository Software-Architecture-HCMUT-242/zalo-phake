from datetime import datetime
from enum import Enum
from typing import List

from pydantic import BaseModel


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

