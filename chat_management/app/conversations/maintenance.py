import logging
from typing import Annotated, Optional, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from .schemas import RecomputeUnreadResponse, UnreadInconsistency, RepairUnreadResponse
from .unread_utils import (
    recompute_all_user_unread_counts,
    find_inconsistent_unread_counts,
    repair_all_unread_counts
)
from ..dependencies import AuthenticatedUser, get_current_active_user, decode_token

logger = logging.getLogger(__name__)

# Create the router for maintenance endpoints
router = APIRouter(
    prefix="/maintenance",
    dependencies=[Depends(decode_token)],
    tags=["Maintenance"]
)

@router.post("/recompute_unread",
             response_model=RecomputeUnreadResponse,
             summary="Recompute unread counts for current user",
             description="Recounts unread messages and fixes user's unread count to ensure consistency.")
async def recompute_user_unread_counts(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
    conversation_id: Optional[str] = None
):
    """
    Recompute unread message counts for the current user
    
    Args:
        current_user: The authenticated user making the request
        conversation_id: Optional ID of a specific conversation to recompute
        
    Returns:
        Dict: Statistics about the recomputation
    """
    try:
        result = await recompute_all_user_unread_counts(current_user.phoneNumber, conversation_id)
        return result
    except Exception as e:
        logger.error(f"Error in recompute_user_unread_counts: {str(e)}")
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to recompute unread counts"
        )

@router.post("/find_inconsistencies", response_model=List[UnreadInconsistency], summary="Find unread count inconsistencies", description="Admin-only endpoint to scan the database and identify inconsistencies between stored unread counts and actual message data.")
async def find_unread_count_inconsistencies(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Find inconsistencies in unread message counts across all conversations
    
    Note: This is an admin-only endpoint that requires special permissions
    
    Args:
        current_user: The authenticated admin user making the request
        
    Returns:
        List[Dict]: List of inconsistencies found
    """
    # Check if user has admin privileges
    # This is a placeholder - implement proper admin check
    is_admin = current_user.isAdmin if hasattr(current_user, 'isAdmin') else False
    
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this operation"
        )
    
    try:
        inconsistencies = await find_inconsistent_unread_counts()
        return inconsistencies
    except Exception as e:
        logger.error(f"Error in find_unread_count_inconsistencies: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to find inconsistencies"
        )

@router.post("/repair_all_unread_counts", response_model=RepairUnreadResponse, summary="Repair all unread count inconsistencies", description="Admin-only endpoint to automatically find and fix all unread count inconsistencies across the database.")
async def repair_unread_counts(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Find and fix all unread count inconsistencies in the database
    
    Note: This is an admin-only endpoint that requires special permissions
    
    Args:
        current_user: The authenticated admin user making the request
        
    Returns:
        Dict: Statistics about the repair operation
    """
    # Check if user has admin privileges
    # This is a placeholder - implement proper admin check
    is_admin = current_user.isAdmin if hasattr(current_user, 'isAdmin') else False
    
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required for this operation"
        )
    
    try:
        result = await repair_all_unread_counts()
        return result
    except Exception as e:
        logger.error(f"Error in repair_unread_counts: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to repair unread counts"
        )
