import logging
from typing import Annotated

import jwt
from app.phone_utils import isVietnamesePhoneNumber
from app.service_env import Environment
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

from .config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

security = HTTPBearer(scheme_name='Authorization')

class AuthenticatedUser(BaseModel):
    phoneNumber: str
    isDiasbled: bool = False

async def get_current_user(token: Annotated[str, Depends(security)]):
    if Environment.is_dev_environment():
        return AuthenticatedUser(phoneNumber=token.credentials)
    
    # TODO: Implement JWT token validation
    raise HTTPException(status_code=401, detail="Not a valid token")
    
async def get_current_active_user(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
):
    if current_user.isDiasbled:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user    

def token_required(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
        
    if Environment.is_dev_environment():
        logger.info(f"Token: {token}")
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