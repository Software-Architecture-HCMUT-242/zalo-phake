import logging

from fastapi import APIRouter
from fastapi import Depends

from ..dependencies import token_required

logger = logging.getLogger(__name__)

# Create the main router for conversations
router = APIRouter(
    dependencies=[Depends(token_required)],
)

