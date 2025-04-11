from fastapi import APIRouter, Depends, HTTPException, Request
from ..dependencies import AuthenticatedUser, get_current_active_user, token_required
from typing import Annotated, List
from .schemas import Group, GroupCreate, GroupUpdate
from ..firebase import firestore_db
from firebase_admin import firestore
from firebase_admin.firestore import FieldFilter
from datetime import datetime
import uuid
import logging
from ..time_utils import convert_timestamps

logger = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(token_required)],
)

@router.post('/groups', response_model=Group)
async def create_group(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)], 
    body: GroupCreate
):
    """
    Create a new group chat with the provided name and members.
    The current user is automatically added as an admin.
    """
    logger.debug(f"Create group request: {body}")
    
    # Validate members list
    if not body.members or len(body.members) < 1:
        raise HTTPException(status_code=400, detail="At least one member is required")
    
    # Ensure current user is in the members list
    if current_user.phoneNumber not in body.members:
        body.members.append(current_user.phoneNumber)
    
    # Generate a new group ID
    group_id = str(uuid.uuid4())
    
    # Create group data
    now = firestore.SERVER_TIMESTAMP
    group_data = {
        "name": body.name,
        "description": body.description or "",
        "members": body.members,
        "admins": [current_user.phoneNumber],  # Current user is the initial admin
        "createdTime": now,
        "lastMessageTime": now,
        "lastMessagePreview": f"Group '{body.name}' created",
        "type": "group"  # To distinguish from one-on-one chats
    }
    
    # Store in Firestore
    group_ref = firestore_db.collection('chats').document(group_id)
    group_ref.set(group_data)
    
    # Get the created group
    group = group_ref.get().to_dict()
    group = convert_timestamps(group)
    
    # Return response
    return Group(
        groupId=group_id,
        name=group['name'],
        description=group['description'],
        members=group['members'],
        admins=group['admins'],
        createdTime=group['createdTime'],
    )

@router.put('/groups/{group_id}', response_model=Group)
async def update_group(
    group_id: str,
    body: GroupUpdate,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Update an existing group's information.
    Only admins can update the group.
    """
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check if user is an admin
    if current_user.phoneNumber not in group_data.get('admins', []):
        raise HTTPException(status_code=403, detail="Only group admins can update the group")
    
    # Update fields that are provided
    update_data = {}
    if body.name is not None:
        update_data['name'] = body.name
    if body.description is not None:
        update_data['description'] = body.description
    if body.members is not None:
        # Ensure current user stays in the group
        if current_user.phoneNumber not in body.members:
            body.members.append(current_user.phoneNumber)
        update_data['members'] = body.members
    
    # Update timestamp
    update_data['lastUpdateTime'] = firestore.SERVER_TIMESTAMP
    
    # Update the document
    group_ref.update(update_data)
    
    # Get the updated group
    updated_group = group_ref.get().to_dict()
    updated_group = convert_timestamps(updated_group)
    
    # Return response
    return Group(
        groupId=group_id,
        name=updated_group['name'],
        description=updated_group.get('description', ''),
        members=updated_group['members'],
        admins=updated_group['admins'],
        createdTime=updated_group['createdTime'],
    )

@router.delete('/groups/{group_id}')
async def delete_group(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Delete a group. Only admins can delete a group.
    """
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check if the user is an admin
    if current_user.phoneNumber not in group_data.get('admins', []):
        raise HTTPException(status_code=403, detail="Only group admins can delete the group")
    
    # Delete the group
    group_ref.delete()
    
    return {"success": True}

@router.post('/groups/{group_id}/members')
async def add_member(
    group_id: str,
    member: dict,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Add a new member to the group. Only admins can add members.
    """
    # Validate request
    if 'phoneNumber' not in member:
        raise HTTPException(status_code=400, detail="phoneNumber is required")
    
    phone_number = member['phoneNumber']
    
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check if the user is an admin
    if current_user.phoneNumber not in group_data.get('admins', []):
        raise HTTPException(status_code=403, detail="Only group admins can add members")
    
    # Check if the member is already in the group
    if phone_number in group_data.get('members', []):
        raise HTTPException(status_code=400, detail="Member is already in the group")
    
    # Add the member
    members = group_data.get('members', [])
    members.append(phone_number)
    
    # Update the group
    group_ref.update({
        'members': members,
        'lastUpdateTime': firestore.SERVER_TIMESTAMP
    })
    
    return {"success": True}

@router.delete('/groups/{group_id}/members/{phone_number}')
async def remove_member(
    group_id: str,
    phone_number: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Remove a member from the group. Admins can remove any member, members can remove themselves.
    """
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check permissions
    is_admin = current_user.phoneNumber in group_data.get('admins', [])
    is_self_removal = current_user.phoneNumber == phone_number
    
    if not (is_admin or is_self_removal):
        raise HTTPException(
            status_code=403, 
            detail="Only admins can remove members, or members can remove themselves"
        )
    
    # Check if the member is in the group
    members = group_data.get('members', [])
    if phone_number not in members:
        raise HTTPException(status_code=404, detail="Member not found in the group")
    
    # Remove the member
    members.remove(phone_number)
    
    # If removing an admin, update admins list too
    admins = group_data.get('admins', [])
    if phone_number in admins:
        admins.remove(phone_number)
        
        # If no admins left, promote the first remaining member to admin
        if not admins and members:
            admins.append(members[0])
    
    # Update the group
    group_ref.update({
        'members': members,
        'admins': admins,
        'lastUpdateTime': firestore.SERVER_TIMESTAMP
    })
    
    return {"success": True}

@router.post('/groups/{group_id}/admins')
async def add_admin(
    group_id: str,
    admin: dict,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Promote a member to admin. Only existing admins can add new admins.
    """
    # Validate request
    if 'phoneNumber' not in admin:
        raise HTTPException(status_code=400, detail="phoneNumber is required")
    
    phone_number = admin['phoneNumber']
    
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check if the current user is an admin
    if current_user.phoneNumber not in group_data.get('admins', []):
        raise HTTPException(status_code=403, detail="Only admins can promote members to admin")
    
    # Check if the user is a member
    if phone_number not in group_data.get('members', []):
        raise HTTPException(status_code=404, detail="User is not a member of the group")
    
    # Check if the user is already an admin
    if phone_number in group_data.get('admins', []):
        raise HTTPException(status_code=400, detail="User is already an admin")
    
    # Add the user to admins
    admins = group_data.get('admins', [])
    admins.append(phone_number)
    
    # Update the group
    group_ref.update({
        'admins': admins,
        'lastUpdateTime': firestore.SERVER_TIMESTAMP
    })
    
    return {"success": True}

@router.delete('/groups/{group_id}/admins/{phone_number}')
async def remove_admin(
    group_id: str,
    phone_number: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Remove admin privileges from a member. Only admins can remove other admins.
    """
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check if the current user is an admin
    if current_user.phoneNumber not in group_data.get('admins', []):
        raise HTTPException(status_code=403, detail="Only admins can demote other admins")
    
    # Check if the user is an admin
    admins = group_data.get('admins', [])
    if phone_number not in admins:
        raise HTTPException(status_code=404, detail="User is not an admin")
    
    # Prevent removing the last admin
    if len(admins) <= 1 and phone_number in admins:
        raise HTTPException(status_code=400, detail="Cannot remove the last admin")
    
    # Remove the user from admins
    admins.remove(phone_number)
    
    # Update the group
    group_ref.update({
        'admins': admins,
        'lastUpdateTime': firestore.SERVER_TIMESTAMP
    })
    
    return {"success": True}

@router.get('/groups/{group_id}', response_model=Group)
async def get_group(
    group_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Get a group's details. Only members can see group details.
    """
    # Get the group
    group_ref = firestore_db.collection('chats').document(group_id)
    group = group_ref.get()
    
    if not group.exists:
        raise HTTPException(status_code=404, detail="Group not found")
    
    group_data = group.to_dict()
    
    # Check if the user is a member
    if current_user.phoneNumber not in group_data.get('members', []):
        raise HTTPException(status_code=403, detail="You are not a member of this group")
    
    # Convert timestamps
    group_data = convert_timestamps(group_data)
    
    # Return response
    return Group(
        groupId=group_id,
        name=group_data['name'],
        description=group_data.get('description', ''),
        members=group_data['members'],
        admins=group_data['admins'],
        createdTime=group_data['createdTime'],
    )