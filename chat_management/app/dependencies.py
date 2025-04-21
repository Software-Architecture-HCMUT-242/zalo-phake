import asyncio
import logging
from pathlib import Path
from typing import Annotated, Any, Dict

from app.phone_utils import is_phone_number, format_phone_number
from app.service_env import Environment
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from firebase_admin import auth

from chat_management.app.firebase import firestore_db

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

async def verify_conversation_participant(
    conversation_id: Annotated[str, Path(description="The ID of the conversation to check participation.")],
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
) -> Dict[str, Any]:
    """
    Dependency that verifies if the current user is a participant
    in the conversation specified by conversation_id.

    Raises:
        HTTPException(404): If the conversation is not found.
        HTTPException(403): If the current user is not a participant.

    Returns:
        The conversation data dictionary if the user is a participant.
    """
    user_id = current_user.phoneNumber
    try:
        conversation_ref = firestore_db.collection('conversations').document(conversation_id)
        # Use asyncio.to_thread for sync Firestore client potentially blocking calls
        conversation = await asyncio.to_thread(conversation_ref.get)

        if not conversation.exists:
            logger.warning(f"Conversation {conversation_id} not found. User: {user_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found"
            )

        conversation_data = conversation.to_dict()
        participants = conversation_data.get('participants', [])

        if user_id not in participants:
            logger.warning(f"User {user_id} is not a participant in conversation {conversation_id}.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not a participant in this conversation"
            )

        logger.debug(f"User {user_id} verified as participant in conversation {conversation_id}.")
        # Return conversation data to potentially avoid fetching it again in the endpoint
        return conversation_data

    except HTTPException:
         # Re-raise HTTP exceptions directly
         raise
    except Exception as e:
        logger.error(f"Error verifying participation for user {user_id} in conv {conversation_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error verifying conversation participation"
        )