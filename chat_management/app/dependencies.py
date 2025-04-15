import logging
from typing import Annotated, Any

from app.phone_utils import isVietnamesePhoneNumber
from app.service_env import Environment
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from firebase_admin import auth

from .config import settings
from .phone_utils import convert_to_vietnamese_phone_number

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

logger = logging.getLogger(__name__)

security = HTTPBearer(scheme_name='Authorization')

class AuthenticatedUser(BaseModel):
    phoneNumber: str
    isDisabled: bool = False

async def decode_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict[str, Any]:
    token = credentials.credentials
        
    if Environment.is_dev_environment():
        logger.info(f"Token: {token}")
        if not isVietnamesePhoneNumber(token):
            raise HTTPException(status_code=401, detail="Not a valid Vietnamese phone number")
        return dict(phoneNumber=convert_to_vietnamese_phone_number(token), isDisabled=False)
    
    try:
        return auth.verify_id_token(token, check_revoked=True)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")
    except auth.ExpiredIdTokenError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except auth.RevokedIdTokenError:
        raise HTTPException(status_code=401, detail="Token has been revoked")
    except auth.InvalidIdTokenError:
        raise HTTPException(status_code=401, detail="Invalid ID token")
    except auth.CertificateFetchError:
        raise HTTPException(status_code=500, detail="Error fetching certificates")
    except auth.UserDisabledError:
        raise HTTPException(status_code=403, detail="User account is disabled")
    except Exception as e:
        logger.error(f"Token verification error: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication error")
    
async def get_current_active_user(
    decoded_token: Annotated[AuthenticatedUser, Depends(decode_token)],
) -> AuthenticatedUser:
    if decoded_token['isDisabled']:
        raise HTTPException(status_code=400, detail="Inactive user")
    return AuthenticatedUser(
        phoneNumber=convert_to_vietnamese_phone_number(decoded_token["phoneNumber"]),
        isDiasbled=decoded_token["isDisabled"]
    )