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
from .routers import chats, messages


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)


PATH_PREFIX = settings.path_prefix
API_VERSION = '/api/v1'
if not PATH_PREFIX.startswith('/'):
    PATH_PREFIX = f'/{PATH_PREFIX}'
if PATH_PREFIX.endswith('/'):
    PATH_PREFIX = PATH_PREFIX.rstrip('/')
PREFIX = f'{PATH_PREFIX}{API_VERSION}'

logger.info(f"Start HTTP server with prefix: {PREFIX}")

app = FastAPI(root_path=PREFIX)
app.include_router(chats.router)
app.include_router(messages.router)
