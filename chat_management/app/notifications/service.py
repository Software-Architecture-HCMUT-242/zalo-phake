import json
import logging
import boto3
from datetime import datetime, timezone
import uuid
from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError
from ..firebase import firestore_db
from ..aws.config import settings

logger = logging.getLogger(__name__)

class NotificationService:
    def __init__(self):
        self.sns = boto3.client(
            'sns',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
    
    async def process_new_message(self, message_data):
        """
        Process a new chat message and send notifications to offline users
        """
        chat_id = message_data.get('chatId')
        message_id = message_data.get('messageId')
        sender_id = message_data.get('senderId')
        content = message_data.get('content')
        participants = message_data.get('participants', [])
        
        if not (chat_id and message_id and sender_id and content and participants):
            logger.error(f"Invalid message data: {message_data}")
            return
        
        # Get chat details for notification
        chat_ref = firestore_db.collection('chats').document(chat_id)
        chat = chat_ref.get()
        
        if not chat.exists:
            logger.error(f"Chat {chat_id} not found")
            return
        
        chat_data = chat.to_dict()
        
        # Get sender name
        sender_ref = firestore_db.collection('users').document(sender_id)
        sender = sender_ref.get()
        sender_name = sender_id
        if sender.exists:
            sender_data = sender.to_dict()
            sender_name = sender_data.get('name', sender_id)
        
        # Send notifications to all participants except sender
        for participant_id in participants:
            if participant_id == sender_id:
                continue
            
            # Check if user is online (has active WebSocket connection)
            # This would be handled by the WebSocket logic
            # Here we'll check a status field in Firestore
            user_ref = firestore_db.collection('users').document(participant_id)
            user = user_ref.get()
            
            if not user.exists:
                continue
            
            user_data = user.to_dict()
            is_online = user_data.get('isOnline', False)
            
            # If user is offline, send push notification
            if not is_online:
                await self._send_push_notification(
                    participant_id, 
                    sender_name, 
                    content, 
                    chat_id,
                    message_id
                )
                
                # Store notification in Firestore for retrieval when user comes online
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
    
    async def _send_push_notification(self, user_id, title, body, chat_id, message_id):
        """
        Send push notification to a user's devices
        """
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
                return
            
            # Check if notifications are muted
            if mute_until and datetime.now(timezone.utc) < mute_until:
                logger.info(f"Notifications muted for user {user_id} until {mute_until}")
                return
        
        # Get user's device tokens
        tokens_ref = firestore_db.collection('device_tokens').where('userId', '==', user_id)
        tokens = tokens_ref.stream()
        
        device_tokens = {}
        for token_doc in tokens:
            token_data = token_doc.to_dict()
            device_type = token_data.get('deviceType')
            token = token_data.get('token')
            
            if device_type and token:
                if device_type not in device_tokens:
                    device_tokens[device_type] = []
                device_tokens[device_type].append(token)
        
        # Send notifications through FCM
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
                            logger.info(f"Successfully sent FCM message: {response}")
                        except FirebaseError as e:
                            logger.error(f"Error sending FCM message: {str(e)}")
                
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
                            self.sns.publish(
                                TopicArn=settings.aws_sns_topic_arn,
                                Message=json.dumps(payload),
                                MessageStructure='json'
                            )
                            logger.info(f"Successfully sent SNS message to {token}")
                        except Exception as e:
                            logger.error(f"Error sending SNS message: {str(e)}")
            
            except Exception as e:
                logger.error(f"Error sending notification to {platform}: {str(e)}")
    
    def _store_notification(self, user_id, type, title, body, data=None):
        """
        Store notification in Firestore for retrieval when user comes online
        """
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
        
        return notification_id