import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from firebase_admin import firestore

from .schemas import Notification, NotificationPreference, DeviceToken
from ..dependencies import get_current_active_user, AuthenticatedUser
from ..firebase import firestore_db
from ..pagination import common_pagination_parameters, PaginatedResponse, PaginationParams

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get('/notifications', response_model=PaginatedResponse[Notification])
async def get_notifications(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)],
    pagination: Annotated[PaginationParams, Depends(common_pagination_parameters)],
    unread_only: bool = Query(False, description="Get only unread notifications")
):
    """
    Get user's notifications with pagination
    """
    user_id = current_user.phoneNumber

    # Query notifications for this user
    notifications_ref = firestore_db.collection('notifications')
    query = notifications_ref.where('userId', '==', user_id).order_by('createdAt', direction='DESCENDING')

    # Filter for unread if requested
    if unread_only:
        query = query.where('isRead', '==', False)

    # Get total count for pagination
    total_docs = query.get()
    total_notifications = len(total_docs)

    # Apply pagination
    paginated_notifs = query.offset((pagination.page - 1) * pagination.size).limit(pagination.size).get()

    notifications = []
    for notif in paginated_notifs:
        notif_data = notif.to_dict()

        # Convert timestamp to datetime if needed
        if isinstance(notif_data.get('createdAt'), firestore.Timestamp):
            notif_data['createdAt'] = notif_data['createdAt'].datetime()

        notifications.append(Notification(**notif_data))

    return PaginatedResponse.create(
        items=notifications,
        total=total_notifications,
        page=pagination.page,
        size=pagination.size
    )

@router.post('/notifications/{notification_id}/read')
async def mark_notification_as_read(
    notification_id: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Mark a notification as read
    """
    user_id = current_user.phoneNumber

    # Get the notification
    notif_ref = firestore_db.collection('notifications').document(notification_id)
    notif = notif_ref.get()

    if not notif.exists:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif_data = notif.to_dict()

    # Verify the notification belongs to the user
    if notif_data.get('userId') != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this notification")

    # If already read, no need to update
    if notif_data.get('isRead', False):
        return {'status': 'success'}

    # Mark as read
    notif_ref.update({'isRead': True})

    # Update user's unread count
    user_ref = firestore_db.collection('users').document(user_id)
    user = user_ref.get()

    if user.exists:
        user_data = user.to_dict()
        unread_count = user_data.get('unreadNotifications', 0)
        if unread_count > 0:
            user_ref.update({'unreadNotifications': unread_count - 1})

    return {'status': 'success'}

@router.post('/notifications/read-all')
async def mark_all_notifications_as_read(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Mark all of user's notifications as read
    """
    user_id = current_user.phoneNumber

    # Get unread notifications
    notifications_ref = firestore_db.collection('notifications')
    unread_notifs = notifications_ref.where('userId', '==', user_id).where('isRead', '==', False).stream()

    # Update each notification
    batch = firestore_db.batch()
    for notif in unread_notifs:
        batch.update(notif.reference, {'isRead': True})

    # Execute batch update
    batch.commit()

    # Reset unread count
    user_ref = firestore_db.collection('users').document(user_id)
    user_ref.update({'unreadNotifications': 0})

    return {'status': 'success'}

@router.get('/notification-preferences', response_model=NotificationPreference)
async def get_notification_preferences(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Get user's notification preferences
    """
    user_id = current_user.phoneNumber

    # Get preferences from Firestore
    pref_ref = firestore_db.collection('notification_preferences').document(user_id)
    pref = pref_ref.get()

    # If preferences don't exist, create default
    if not pref.exists:
        default_prefs = NotificationPreference(userId=user_id)
        pref_ref.set(default_prefs.dict())
        return default_prefs

    pref_data = pref.to_dict()

    # Convert timestamp to datetime if needed
    if isinstance(pref_data.get('muteUntil'), firestore.Timestamp):
        pref_data['muteUntil'] = pref_data['muteUntil'].datetime()

    return NotificationPreference(**pref_data)

@router.put('/notification-preferences', response_model=NotificationPreference)
async def update_notification_preferences(
    preferences: NotificationPreference,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Update user's notification preferences
    """
    user_id = current_user.phoneNumber

    # Ensure the userId in the data matches the authenticated user
    if preferences.userId != user_id:
        raise HTTPException(status_code=400, detail="UserId in preferences does not match authenticated user")

    # Update preferences in Firestore
    pref_ref = firestore_db.collection('notification_preferences').document(user_id)
    pref_ref.set(preferences.dict())

    return preferences

@router.post('/device-tokens', response_model=DeviceToken)
async def register_device_token(
    device_token: DeviceToken,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Register a device token for push notifications
    """
    user_id = current_user.phoneNumber

    # Ensure the userId in the data matches the authenticated user
    if device_token.userId != user_id:
        raise HTTPException(status_code=400, detail="UserId in device token does not match authenticated user")

    # Check if token already exists
    tokens_ref = firestore_db.collection('device_tokens')
    query = tokens_ref.where('userId', '==', user_id).where('token', '==', device_token.token).limit(1)
    existing_tokens = list(query.stream())

    if existing_tokens:
        # Update existing token
        token_doc = existing_tokens[0]
        token_doc.reference.update({
            'deviceType': device_token.deviceType,
            'lastUpdated': datetime.now(timezone.utc)
        })
        device_token.lastUpdated = datetime.now(timezone.utc)
    else:
        # Create new token entry
        device_token.lastUpdated = datetime.now(timezone.utc)
        tokens_ref.add(device_token.dict())

    return device_token

@router.delete('/device-tokens/{token}')
async def delete_device_token(
    token: str,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_active_user)]
):
    """
    Delete a device token when logging out or uninstalling app
    """
    user_id = current_user.phoneNumber

    # Find token document
    tokens_ref = firestore_db.collection('device_tokens')
    query = tokens_ref.where('userId', '==', user_id).where('token', '==', token).limit(1)
    tokens = list(query.stream())

    if not tokens:
        raise HTTPException(status_code=404, detail="Device token not found")

    # Delete token
    tokens[0].reference.delete()

    return {'status': 'success'}