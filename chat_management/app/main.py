import logging
import os

from app.config import settings, get_prefix
from fastapi import FastAPI

from .chats.router import router as chats_router
from .groups.router import router as groups_router
from .messages.router import router as messages_router

# import all you need from fastapi-pagination

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# Print all environment variables
for key, value in os.environ.items():
    print(f"{key}: {value}")

logger = logging.getLogger(__name__)


API_VERSION = '/api/v1'
PREFIX = get_prefix(API_VERSION)

logger.info(f"Start HTTP server with prefix: {PREFIX}")

app = FastAPI(root_path=PREFIX)
app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(groups_router)