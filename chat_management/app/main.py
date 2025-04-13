import logging
import os

from app.config import get_prefix
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .conversations import all_router as conversations_routers
from .notifications.router import router as notifications_router
from .ws.router import router as ws_router

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
for router in conversations_routers:
    app.include_router(router)
# app.include_router(messages_router)
# app.include_router(groups_router)
app.include_router(notifications_router)
app.include_router(ws_router)