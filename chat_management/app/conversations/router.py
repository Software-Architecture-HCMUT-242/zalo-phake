from fastapi import APIRouter, Depends

from ..dependencies import token_required

# Create the main router for conversations
router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(token_required)],
)
