import logging
import os

from app.config import settings, get_prefix
from fastapi import FastAPI

from .chats.router import router as chats_router
from .conversations.router import router as conversations_router
from .groups.router import router as groups_router
from .messages.router import router as messages_router
from .notifications.router import router as notifications_router
from .ws.router import router as ws_router
from fastapi.middleware.cors import CORSMiddleware


# import all you need from fastapi-pagination

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

origins = [
    "*"
]

# Print all environment variables
for key, value in os.environ.items():
    print(f"{key}: {value}")

logger = logging.getLogger(__name__)


API_VERSION = '/api/v1'
PREFIX = get_prefix(API_VERSION)

logger.info(f"Start HTTP server with prefix: {PREFIX}")

app = FastAPI(root_path=PREFIX)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for monitoring and deployment verification
    """
    return {"status": "healthy", "version": "1.0.0"}

# app.include_router(chats_router)
app.include_router(conversations_router)
# app.include_router(messages_router)
# app.include_router(groups_router)
app.include_router(notifications_router)
app.include_router(ws_router)