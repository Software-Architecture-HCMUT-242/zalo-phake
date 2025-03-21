from app.service_env import Environment
from typing import Union
import os
from app.phone_utils import isVietnamesePhoneNumber

from fastapi import FastAPI, Query
from datetime import datetime, timezone
from functools import wraps
import jwt

from fastapi import Depends, HTTPException
from pydantic_settings import BaseSettings
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

security = HTTPBearer()

def token_required(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    if Environment.is_dev_environment():
        logger.info(f"Token: {token}")
        
    if Environment.is_dev_environment():
        if not isVietnamesePhoneNumber(token):
            raise HTTPException(status_code=401, detail="Not a valid Vietnamese phone number")
        return
    
    try:
        # You'll need to set up your secret key and implement proper JWT validation
        jwt.decode(token, settings.fastapi_secret_key, algorithms=['HS256'])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token is invalid")