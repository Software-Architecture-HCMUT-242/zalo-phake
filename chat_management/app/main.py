from app.service_env import Environment
from typing import Union
import os
from app.phone_utils import isVietnamesePhoneNumber

from fastapi import FastAPI, Query
from datetime import datetime, timezone
from functools import wraps
import jwt

from fastapi import Depends, HTTPException, Request
from pydantic_settings import BaseSettings
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
from app.config import settings
from .messages.router import router as messages_router
from .chats.router import router as chats_router
# import all you need from fastapi-pagination
from fastapi_pagination import Page, add_pagination, paginate


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


def get_prefix(path_prefix: str, api_version: str) -> str:
    if not path_prefix.startswith('/'):
        path_prefix = f'/{path_prefix}'
    if path_prefix.endswith('/'):
        path_prefix = path_prefix.rstrip('/')
    return f'{path_prefix}{api_version}'

PATH_PREFIX = settings.path_prefix
API_VERSION = '/api/v1'
PREFIX = get_prefix(PATH_PREFIX, API_VERSION)

logger.info(f"Start HTTP server with prefix: {PREFIX}")

app = FastAPI(root_path=PREFIX)
app.include_router(chats_router)
app.include_router(messages_router)

add_pagination(app)