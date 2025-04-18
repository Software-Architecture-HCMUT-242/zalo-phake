import logging
from typing import Annotated, Any

from app.phone_utils import is_phone_number, format_phone_number
from app.service_env import Environment
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from firebase_admin import auth

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
        if not is_phone_number(token):
            raise HTTPException(status_code=401, detail="Not a valid Vietnamese phone number")
        return dict(phone_number=format_phone_number(token), is_disabled=False)
    
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
    return AuthenticatedUser(
        phoneNumber=format_phone_number(decoded_token["phone_number"]),
        isDiasbled=False
    )