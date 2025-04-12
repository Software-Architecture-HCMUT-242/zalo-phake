import json
import logging
import uuid
from datetime import datetime, timezone

import boto3
from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError

from ..aws import sqs_client
from ..aws.config import settings
from ..firebase import firestore_db

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        """
        Initialize the notification service with SNS client for push notifications
        """
        self.sns = boto3.client(
            'sns',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        logger.info("NotificationService initialized")

    async def send_message_to_queue(self, message_data):
        """
        Send a message to the SQS queue for asynchronous processing
        """
        try:
            # Validate required fields
            required_fields = ['event', 'chatId', 'messageId', 'senderId', 'content']
            for field in required_fields:
                if field not in message_data:
                    logger.error(f"Missing required field: {field} in message data")
                    return False

            # Make timestamp serializable if it's a datetime object
            if 'timestamp' in message_data and isinstance(message_data['timestamp'], datetime):
                message_data['timestamp'] = message_data['timestamp'].isoformat()

            # Send to SQS
            response = sqs_client.send_message(
                queue_url=settings.aws_sqs_queue_url,
                message_body=message_data
            )

            logger.info(f"Message sent to SQS queue. MessageId: {response.get('MessageId')}")
            return True
        except Exception as e:
            logger.error(f"Error sending message to SQS queue: {str(e)}")
            return False

    async def process_new_message(self, message_data):
        """
        Process a new chat message and send notifications to offline users
        This might be called directly or by a worker processing SQS messages
        """
        try:
            chat_id = message_data.get('chatId')
            message_id = message_data.get('messageId')
            sender_id = message_data.get('senderId')
            content = message_data.get('content')
            participants = message_data.get('participants', [])

            if not (chat_id and message_id and sender_id and content and participants):
                logger.error(f"Invalid message data: {message_data}")
                return False

            # Get chat details for notification
            chat_ref = firestore_db.collection('chats').document(chat_id)
            chat = chat_ref.get()

            if not chat.exists:
                logger.error(f"Chat {chat_id} not found")
                return False

            chat_data = chat.to_dict()

            # Get sender name
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)

            # Send notifications to all participants except sender
            notification_tasks = []
            for participant_id in participants:
                if participant_id == sender_id:
                    continue

                # Check if user is online (has active WebSocket connection)
                user_ref = firestore_db.collection('users').document(participant_id)
                user = user_ref.get()

                if not user.exists:
                    continue

                user_data = user.to_dict()
                is_online = user_data.get('isOnline', False)

                # If user is offline, send push notification
                if not is_online:
                    # Check notification preferences
                    should_send_push = await self._check_notification_preferences(participant_id, 'message')

                    if should_send_push:
                        notification_tasks.append(self._send_push_notification(
                            participant_id,
                            sender_name,
                            content[:100] + ('...' if len(content) > 100 else ''),
                            chat_id,
                            message_id
                        ))

                    # Store notification in Firestore regardless of push settings
                    self._store_notification(
                        participant_id,
                        'message',
                        sender_name,
                        content,
                        {
                            'chatId': chat_id,
                            'messageId': message_id,
                            'senderId': sender_id
                        }
                    )

            # Execute all notification tasks
            for task in notification_tasks:
                await task

            return True

        except Exception as e:
            logger.error(f"Error processing new message notification: {str(e)}")
            return False

    async def _check_notification_preferences(self, user_id, notification_type):
        """
        Check if a user has enabled notifications for this type
        """
        try:
            pref_ref = firestore_db.collection('notification_preferences').document(user_id)
            pref = pref_ref.get()

            if pref.exists:
                pref_data = pref.to_dict()

                # Check if push notifications are enabled
                push_enabled = pref_data.get('pushEnabled', True)
                if not push_enabled:
                    return False

                # Check if notifications are muted
                mute_until = pref_data.get('muteUntil')
                if mute_until and datetime.now(timezone.utc) < mute_until:
                    return False

                # Check for specific notification type
                if notification_type == 'message':
                    return pref_data.get('messageNotifications', True)
                elif notification_type == 'group_invitation':
                    return pref_data.get('groupNotifications', True)
                elif notification_type == 'friend_request':
                    return pref_data.get('friendRequestNotifications', True)
                elif notification_type == 'system':
                    return pref_data.get('systemNotifications', True)

            # Default to enabled if no preferences found
            return True

        except Exception as e:
            logger.error(f"Error checking notification preferences for user {user_id}: {str(e)}")
            return True  # Default to True in case of error

    async def _send_push_notification(self, user_id, title, body, chat_id, message_id):
        """
        Send push notification to a user's devices
        """
        try:
            # Check user notification preferences
            pref_ref = firestore_db.collection('notification_preferences').document(user_id)
            pref = pref_ref.get()

            if pref.exists:
                pref_data = pref.to_dict()
                push_enabled = pref_data.get('pushEnabled', True)
                message_notifications = pref_data.get('messageNotifications', True)
                mute_until = pref_data.get('muteUntil')

                if not push_enabled or not message_notifications:
                    logger.info(f"Push notifications disabled for user {user_id}")
                    return False

                # Check if notifications are muted
                if mute_until and datetime.now(timezone.utc) < mute_until:
                    logger.info(f"Notifications muted for user {user_id} until {mute_until}")
                    return False

            # Get user's device tokens
            tokens_ref = firestore_db.collection('device_tokens')
            query = tokens_ref.where('userId', '==', user_id)
            device_tokens_docs = query.stream()

            device_tokens = {}
            for token_doc in device_tokens_docs:
                token_data = token_doc.to_dict()
                device_type = token_data.get('deviceType')
                token = token_data.get('token')

                if device_type and token:
                    if device_type not in device_tokens:
                        device_tokens[device_type] = []
                    device_tokens[device_type].append(token)

            # Send notifications through appropriate channels based on device type
            for platform, tokens in device_tokens.items():
                try:
                    # For iOS and Android, use Firebase Cloud Messaging
                    if platform in ['ios', 'android']:
                        for token in tokens:
                            message = messaging.Message(
                                notification=messaging.Notification(
                                    title=title,
                                    body=body
                                ),
                                data={
                                    'chatId': chat_id,
                                    'messageId': message_id
                                },
                                token=token
                            )

                            try:
                                response = messaging.send(message)
                                logger.info(f"Successfully sent FCM message to {platform} device: {response}")
                            except FirebaseError as e:
                                logger.error(f"Error sending FCM message to {platform} device: {str(e)}")
                                # Handle invalid tokens
                                if "registration-token-not-registered" in str(e).lower():
                                    self._remove_invalid_token(user_id, token)

                    # For web, use SNS
                    elif platform == 'web':
                        for token in tokens:
                            payload = {
                                'default': f"New message from {title}",
                                'GCM': json.dumps({
                                    'notification': {
                                        'title': title,
                                        'body': body
                                    },
                                    'data': {
                                        'chatId': chat_id,
                                        'messageId': message_id
                                    }
                                })
                            }

                            try:
                                # Verify SNS topic ARN is configured
                                sns_topic_arn = getattr(settings, 'aws_sns_topic_arn', None)
                                if not sns_topic_arn:
                                    logger.error("SNS topic ARN is not configured")
                                    continue

                                self.sns.publish(
                                    TopicArn=sns_topic_arn,
                                    Message=json.dumps(payload),
                                    MessageStructure='json'
                                )
                                logger.info(f"Successfully sent SNS message to web client: {token}")
                            except Exception as e:
                                logger.error(f"Error sending SNS message: {str(e)}")

                except Exception as e:
                    logger.error(f"Error sending notification to {platform}: {str(e)}")

            return True

        except Exception as e:
            logger.error(f"Error in send_push_notification: {str(e)}")
            return False

    def _remove_invalid_token(self, user_id, token):
        """
        Remove an invalid device token from the database
        """
        try:
            tokens_ref = firestore_db.collection('device_tokens')
            query = tokens_ref.where('userId', '==', user_id).where('token', '==', token)
            invalid_tokens = list(query.stream())

            for invalid_token in invalid_tokens:
                invalid_token.reference.delete()
                logger.info(f"Removed invalid token for user {user_id}: {token}")
        except Exception as e:
            logger.error(f"Error removing invalid token: {str(e)}")

    def _store_notification(self, user_id, type, title, body, data=None):
        """
        Store notification in Firestore for retrieval when user comes online
        """
        try:
            notification_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)

            notification_data = {
                'notificationId': notification_id,
                'userId': user_id,
                'type': type,
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