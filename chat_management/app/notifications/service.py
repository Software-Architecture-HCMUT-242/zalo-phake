import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from .schemas import NotificationEvent, NotificationRecipient, DeliveryChannel
from ..aws import sqs_utils
from ..firebase import firestore_db

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self):
        """
        Initialize the notification service
        """
        logger.info("NotificationService initialized")

    async def send_notification_event(self, event_type: str, payload: Dict[str, Any],
                                      recipients: List[str], delivery_channels: List[str] = None) -> bool:
        """
        Create and send a standardized notification event to SQS queue

        Args:
            event_type: Type of notification event (new_message, group_invitation, etc.)
            payload: Event payload data
            recipients: List of recipient user IDs
            delivery_channels: List of delivery channels (defaults to both PUSH and IN_APP)

        Returns:
            bool: True if event was successfully sent to SQS, False otherwise
        """
        try:
            # Set default delivery channels if none provided
            if delivery_channels is None:
                delivery_channels = [DeliveryChannel.PUSH, DeliveryChannel.IN_APP]

            # Generate event ID if not already in payload
            event_id = payload.get('messageId', str(uuid.uuid4()))
            if 'eventId' not in payload:
                payload['eventId'] = event_id

            # Format recipients according to the standardized schema
            recipient_objects = [
                NotificationRecipient(
                    userId=user_id,
                    deliveryChannels=delivery_channels
                ) for user_id in recipients
            ]

            # Create standardized notification event
            notification_event = NotificationEvent(
                eventId=event_id,
                eventType=event_type,
                timestamp=datetime.now(timezone.utc),
                payload=payload,
                recipients=recipient_objects
            )

            # Convert to dictionary for sending to SQS
            event_dict = notification_event.model_dump()

            # Use asyncio.create_task to avoid blocking
            task = asyncio.create_task(
                sqs_utils.send_to_sqs(
                    event_type=event_type,
                    payload=event_dict
                )
            )

            # Log the event
            logger.info(f"Sent {event_type} notification event to SQS queue: {event_id}")

            return True

        except Exception as e:
            logger.error(f"Error sending notification event to SQS: {str(e)}")
            return False

    async def process_new_message(self, message_data: Dict[str, Any]) -> bool:
        """
        Process a new chat message notification

        Args:
            message_data: Message data dictionary

        Returns:
            bool: True if notification was successfully processed
        """
        try:
            # Extract necessary data from the payload
            conversation_id = message_data.get('conversationId')
            message_id = message_data.get('messageId')
            sender_id = message_data.get('senderId')
            content = message_data.get('content')
            participants = message_data.get('participants', [])

            if not all([conversation_id, message_id, sender_id, content, participants]):
                logger.error(f"Invalid message data: {message_data}")
                return False

            # Get conversation details for notification
            conversation_ref = firestore_db.collection('conversations').document(conversation_id)
            conversation = conversation_ref.get()

            if not conversation.exists:
                logger.error(f"Conversation {conversation_id} not found")
                return False

            # Get sender name
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)

            # Create payload for notification event
            payload = {
                'conversationId': conversation_id,
                'messageId': message_id,
                'senderId': sender_id,
                'senderName': sender_name,
                'content': content,
                'contentType': message_data.get('messageType', 'text')
            }

            # Determine recipients (all participants except sender)
            recipients = [p for p in participants if p != sender_id]

            if not recipients:
                logger.info(f"No recipients to notify for message {message_id}")
                return True

            # Send notification event to SQS queue
            event_sent = await self.send_notification_event(
                event_type='new_message',
                payload=payload,
                recipients=recipients
            )

            # Store notifications in Firestore for each recipient
            storage_tasks = []
            for recipient_id in recipients:
                storage_tasks.append(self._store_notification(
                    recipient_id,
                    'message',
                    sender_name,
                    content[:100] + ('...' if len(content) > 100 else ''),
                    {
                        'conversationId': conversation_id,
                        'messageId': message_id,
                        'senderId': sender_id
                    }
                ))

            # Wait for all storage tasks to complete
            for task in storage_tasks:
                await task

            return event_sent

        except Exception as e:
            logger.error(f"Error processing new message notification: {str(e)}")
            return False

    async def process_group_invitation(self, invitation_data: Dict[str, Any]) -> bool:
        """
        Process a group invitation notification

        Args:
            invitation_data: Group invitation data dictionary

        Returns:
            bool: True if notification was successfully processed
        """
        try:
            # Extract necessary data from the payload
            conversation_id = invitation_data.get('conversationId')
            sender_id = invitation_data.get('senderId')
            invitee_id = invitation_data.get('inviteeId')
            group_name = invitation_data.get('groupName', 'a group')

            if not all([conversation_id, sender_id, invitee_id]):
                logger.error(f"Invalid group invitation data: {invitation_data}")
                return False

            # Get sender name
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)

            # Prepare notification content
            title = f"{sender_name}"
            body = f"invited you to join {group_name}"

            # Create payload for notification event
            payload = {
                'conversationId': conversation_id,
                'senderId': sender_id,
                'senderName': sender_name,
                'inviteeId': invitee_id,
                'groupName': group_name
            }

            # Send notification event to SQS queue
            event_sent = await self.send_notification_event(
                event_type='group_invitation',
                payload=payload,
                recipients=[invitee_id]
            )

            # Store notification in Firestore
            await self._store_notification(
                invitee_id,
                'group_invitation',
                title,
                body,
                {
                    'conversationId': conversation_id,
                    'senderId': sender_id,
                    'type': 'group_invitation'
                }
            )

            return event_sent

        except Exception as e:
            logger.error(f"Error processing group invitation notification: {str(e)}")
            return False

    async def process_friend_request(self, request_data: Dict[str, Any]) -> bool:
        """
        Process a friend request notification

        Args:
            request_data: Friend request data dictionary

        Returns:
            bool: True if notification was successfully processed
        """
        try:
            # Extract necessary data from the payload
            sender_id = request_data.get('senderId')
            recipient_id = request_data.get('recipientId')

            if not all([sender_id, recipient_id]):
                logger.error(f"Invalid friend request data: {request_data}")
                return False

            # Get sender name
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)

            # Prepare notification content
            title = f"{sender_name}"
            body = "sent you a friend request"

            # Create payload for notification event
            payload = {
                'senderId': sender_id,
                'senderName': sender_name,
                'recipientId': recipient_id
            }

            # Send notification event to SQS queue
            event_sent = await self.send_notification_event(
                event_type='friend_request',
                payload=payload,
                recipients=[recipient_id]
            )

            # Store notification in Firestore
            await self._store_notification(
                recipient_id,
                'friend_request',
                title,
                body,
                {
                    'senderId': sender_id,
                    'type': 'friend_request'
                }
            )

            return event_sent

        except Exception as e:
            logger.error(f"Error processing friend request notification: {str(e)}")
            return False

    async def _store_notification(self, user_id: str, notification_type: str,
                                  title: str, body: str, data: Optional[Dict] = None) -> str:
        """
        Store notification in Firestore for retrieval

        Args:
            user_id: User ID to store notification for
            notification_type: Type of notification (message, group_invitation, etc.)
            title: Notification title
            body: Notification body/content
            data: Additional notification data

        Returns:
            str: Notification ID if successfully stored, None otherwise
        """
        try:
            notification_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            notification_data = {
                'notificationId': notification_id,
                'userId': user_id,
                'type': notification_type,
                'title': title,
                'body': body,
                'data': data,
                'isRead': False,
                'createdAt': now
            }

            # Store in Firestore
            notif_ref = firestore_db.collection('notifications').document(notification_id)
            notif_ref.set(notification_data)

            # Update user's unread notification count
            user_ref = firestore_db.collection('users').document(user_id)
            user = user_ref.get()

            if user.exists:
                user_data = user.to_dict()
                unread_count = user_data.get('unreadNotifications', 0)
                user_ref.update({'unreadNotifications': unread_count + 1})

            logger.info(f"Stored notification {notification_id} for user {user_id}")
            return notification_id

        except Exception as e:
            logger.error(f"Error storing notification: {str(e)}")
            return None