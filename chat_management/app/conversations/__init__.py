from .conversations import router as conversations
from .maintenance import router as maintenance
from .members import router as members
from .messages_get import router as messages_get
from .messages_read import router as messages_read
from .messages_send import router as messages_send
from .messages_typing import router as messages_typing

all_router = [
    conversations,
    members,
    maintenance,
    messages_get,
    messages_send,
    messages_typing,
    messages_read,
]
