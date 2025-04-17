import asyncio
import json
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import uuid

import boto3
from firebase_admin import messaging, firestore
from firebase_admin.exceptions import FirebaseError

from ..aws.config import settings
from ..firebase import firestore_db
from ..notifications.schemas import NotificationType

logger = logging.getLogger(__name__)

# Constants for retry logic
MAX_RETRY_COUNT = 5
BASE_RETRY_DELAY = 60  # seconds
MAX_RETRY_DELAY = 3600  # 1 hour


class NotificationConsumerService:
    """
    Service for consuming notification events from SQS, processing them according
    to user preferences, and sending via appropriate channels
    """

    def __init__(self):
        """Initialize the Notification Consumer Service"""
        # Initialize AWS SQS client
        self.sqs_client = boto3.client(
            'sqs',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        
        # Initialize AWS SNS client for web push notifications
        self.sns_client = boto3.client(
            'sns',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        
        # Queue URLs
        self.main_queue_url = settings.aws_sqs_queue_url
        self.retry_queue_url = self.main_queue_url.replace('zalo-phake-notifications', 'zalo-phake-notifications-retry')
        self.dlq_url = self.main_queue_url.replace('zalo-phake-notifications', 'zalo-phake-notifications-dlq')
        
        logger.info("NotificationConsumerService initialized")

    async def start_processing(self):
        """
        Start the main processing loop that continuously polls SQS for new messages
        """
        logger.info("Starting notification consumer service")
        
        while True:
            try:
                # Process main queue
                await self._process_queue(self.main_queue_url)
                
                # Process retry queue less frequently
                await self._process_queue(self.retry_queue_url)
                
                # Small delay to prevent aggressive polling
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in main processing loop: {str(e)}")
                logger.error(traceback.format_exc())
                # Add a delay before retrying after an error
                await asyncio.sleep(5)

    async def _process_queue(self, queue_url: str):
        """
        Process messages from a specific SQS queue
        
        Args:
            queue_url: The URL of the SQS queue to process
        """
        try:
            # Receive messages from SQS
            response = await asyncio.to_thread(
                self.sqs_client.receive_message,
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,  # Process up to 10 messages at once
                WaitTimeSeconds=5,       # Use long polling to reduce costs
                VisibilityTimeout=60     # 1 minute to process before message becomes visible again
            )
            
            messages = response.get('Messages', [])
            if not messages:
                return  # No messages to process
                
            logger.info(f"Received {len(messages)} messages from {queue_url}")
            
            # Process each message
            for message in messages:
                try:
                    receipt_handle = message.get('ReceiptHandle')
                    body = message.get('Body', '{}')
                    
                    # Parse and validate the message
                    try:
                        event_data = json.loads(body)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON in message body: {body}")
                        await self._delete_message(queue_url, receipt_handle)
                        continue
                        
                    # Process the notification event based on its type
                    event_type = event_data.get('event')
                    success = False
                    
                    if event_type == 'new_message':
                        success = await self._process_new_message(event_data)
                    elif event_type == 'group_invitation':
                        success = await self._process_group_invitation(event_data)
                    elif event_type == 'friend_request':
                        success = await self._process_friend_request(event_data)
                    elif event_type == 'direct_conversation_created':
                        success = await self._process_direct_conversation_created(event_data)
                    elif event_type == 'group_conversation_created':
                        success = await self._process_group_conversation_created(event_data)
                    else:
                        logger.warning(f"Unknown event type: {event_type}")
                        # Delete unknown event types to prevent queue clogging
                        await self._delete_message(queue_url, receipt_handle)
                        continue
                        
                    if success:
                        # If processing was successful, delete the message from the queue
                        await self._delete_message(queue_url, receipt_handle)
                    else:
                        # If processing failed, handle the retry logic
                        await self._handle_failed_message(queue_url, event_data, receipt_handle)
                        
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
                    logger.error(traceback.format_exc())
                    
                    # Get the receipt handle if it exists
                    receipt_handle = message.get('ReceiptHandle', None)
                    if receipt_handle:
                        # Try to handle the failed message for retry
                        try:
                            event_data = json.loads(body)
                            await self._handle_failed_message(queue_url, event_data, receipt_handle)
                        except Exception as retry_error:
                            logger.error(f"Error handling failed message: {str(retry_error)}")
                            # If we can't even handle the retry, delete the message to prevent queue clogging
                            await self._delete_message(queue_url, receipt_handle)
                    
        except Exception as e:
            logger.error(f"Error processing queue {queue_url}: {str(e)}")
            logger.error(traceback.format_exc())

    async def _delete_message(self, queue_url: str, receipt_handle: str):
        """
        Delete a message from the SQS queue
        
        Args:
            queue_url: The URL of the SQS queue
            receipt_handle: The receipt handle of the message to delete
        """
        try:
            await asyncio.to_thread(
                self.sqs_client.delete_message,
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle
            )
        except Exception as e:
            logger.error(f"Error deleting message from queue {queue_url}: {str(e)}")

    async def _handle_failed_message(self, queue_url: str, event_data: Dict[str, Any], receipt_handle: str):
        """
        Handle a failed message by implementing retry logic with exponential backoff
        
        Args:
            queue_url: The URL of the source SQS queue
            event_data: The event data that failed processing
            receipt_handle: The receipt handle of the message in the source queue
        """
        try:
            # Increment retry count
            retry_count = event_data.get('retryCount', 0) + 1
            event_data['retryCount'] = retry_count
            
            if retry_count <= MAX_RETRY_COUNT:
                # Calculate backoff delay with exponential increase and some jitter
                delay_seconds = min(
                    BASE_RETRY_DELAY * (2 ** (retry_count - 1)) + (retry_count * 7),
                    MAX_RETRY_DELAY
                )
                
                # Send to retry queue with delay
                await asyncio.to_thread(
                    self.sqs_client.send_message,
                    QueueUrl=self.retry_queue_url,
                    MessageBody=json.dumps(event_data),
                    DelaySeconds=delay_seconds
                )
                
                logger.info(f"Message sent to retry queue with {delay_seconds}s delay (retry {retry_count}/{MAX_RETRY_COUNT})")
                
                # Delete from the source queue
                await self._delete_message(queue_url, receipt_handle)
            else:
                # Exceeded retry limit, send to dead-letter queue for manual inspection
                await asyncio.to_thread(
                    self.sqs_client.send_message,
                    QueueUrl=self.dlq_url,
                    MessageBody=json.dumps(event_data)
                )
                
                logger.warning(f"Message exceeded retry limit and was sent to DLQ: {json.dumps(event_data)}")
                
                # Delete from the source queue
                await self._delete_message(queue_url, receipt_handle)
                
        except Exception as e:
            logger.error(f"Error handling failed message: {str(e)}")

    async def _process_new_message(self, event_data: Dict[str, Any]) -> bool:
        """
        Process a new message notification
        
        Args:
            event_data: The event data containing message details
            
        Returns:
            bool: True if processing was successful, False otherwise
        """
        try:
            # Extract necessary data
            conversation_id = event_data.get('conversationId')
            message_id = event_data.get('messageId')
            sender_id = event_data.get('senderId')
            content = event_data.get('content')
            participants = event_data.get('participants', [])
            
            # Validate required fields
            if not all([conversation_id, message_id, sender_id, content, participants]):
                logger.error(f"Missing required fields in message data: {event_data}")
                return False
                
            logger.info(f"Processing new message notification for conversation {conversation_id}")
            
            # Get conversation details for notification context
            conversation_ref = firestore_db.collection('conversations').document(conversation_id)
            conversation = conversation_ref.get()
            
            if not conversation.exists:
                logger.error(f"Conversation {conversation_id} not found")
                return False
                
            # Get sender details
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id  # Default to sender ID if name not found
            
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)
                
            # Track successful notifications
            notification_success = True
            
            # Process notification for each participant (except sender)
            for participant_id in participants:
                if participant_id == sender_id:
                    continue  # Skip sender
                    
                # Check if user is online (has active WebSocket connection)
                user_ref = firestore_db.collection('users').document(participant_id)
                user = user_ref.get()
                
                if not user.exists:
                    logger.warning(f"User {participant_id} not found, skipping notification")
                    continue
                    
                user_data = user.to_dict()
                is_online = user_data.get('isOnline', False)
                
                # If user is offline, send push notification
                if not is_online:
                    # Check notification preferences
                    should_notify = await self._check_notification_preferences(
                        participant_id, 
                        NotificationType.MESSAGE
                    )
                    
                    if should_notify:
                        # Send push notification
                        success = await self._send_push_notification(
                            participant_id,
                            sender_name,
                            content[:100] + ('...' if len(content) > 100 else ''),
                            {
                                'conversationId': conversation_id,
                                'messageId': message_id,
                                'senderId': sender_id,
                                'type': 'message'
                            }
                        )
                        notification_success = notification_success and success
                        
                    # Store notification in database regardless of push preference
                    await self._store_notification(
                        participant_id,
                        NotificationType.MESSAGE,
                        sender_name,
                        content,
                        {
                            'conversationId': conversation_id,
                            'messageId': message_id,
                            'senderId': sender_id
                        }
                    )
                    
            return notification_success
            
        except Exception as e:
            logger.error(f"Error processing new message notification: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def _process_group_invitation(self, event_data: Dict[str, Any]) -> bool:
        """
        Process a group invitation notification
        
        Args:
            event_data: The event data containing invitation details
            
        Returns:
            bool: True if processing was successful, False otherwise
        """
        try:
            # Extract necessary data
            conversation_id = event_data.get('conversationId')
            sender_id = event_data.get('senderId')
            invitee_id = event_data.get('inviteeId')
            group_name = event_data.get('groupName', 'a group')
            
            # Validate required fields
            if not all([conversation_id, sender_id, invitee_id]):
                logger.error(f"Missing required fields in group invitation data: {event_data}")
                return False
                
            logger.info(f"Processing group invitation for {invitee_id} to group {conversation_id}")
            
            # Get sender details
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id  # Default to sender ID if name not found
            
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)
                
            # Check if user is online
            user_ref = firestore_db.collection('users').document(invitee_id)
            user = user_ref.get()
            
            if not user.exists:
                logger.warning(f"User {invitee_id} not found, skipping notification")
                return False
                
            user_data = user.to_dict()
            is_online = user_data.get('isOnline', False)
            
            # Prepare notification content
            title = f"{sender_name}"
            body = f"invited you to join {group_name}"
            
            # If user is offline, send push notification
            if not is_online:
                # Check notification preferences
                should_notify = await self._check_notification_preferences(
                    invitee_id, 
                    NotificationType.GROUP_INVITATION
                )
                
                if should_notify:
                    # Send push notification
                    await self._send_push_notification(
                        invitee_id,
                        title,
                        body,
                        {
                            'conversationId': conversation_id,
                            'senderId': sender_id,
                            'type': 'group_invitation'
                        }
                    )
                    
                # Store notification in database
                await self._store_notification(
                    invitee_id,
                    NotificationType.GROUP_INVITATION,
                    title,
                    body,
                    {
                        'conversationId': conversation_id,
                        'senderId': sender_id
                    }
                )
                
            return True
            
        except Exception as e:
            logger.error(f"Error processing group invitation: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def _process_friend_request(self, event_data: Dict[str, Any]) -> bool:
        """
        Process a friend request notification
        
        Args:
            event_data: The event data containing friend request details
            
        Returns:
            bool: True if processing was successful, False otherwise
        """
        try:
            # Extract necessary data
            sender_id = event_data.get('senderId')
            recipient_id = event_data.get('recipientId')
            
            # Validate required fields
            if not all([sender_id, recipient_id]):
                logger.error(f"Missing required fields in friend request data: {event_data}")
                return False
                
            logger.info(f"Processing friend request from {sender_id} to {recipient_id}")
            
            # Get sender details
            sender_ref = firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id  # Default to sender ID if name not found
            
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)
                
            # Check if recipient is online
            user_ref = firestore_db.collection('users').document(recipient_id)
            user = user_ref.get()
            
            if not user.exists:
                logger.warning(f"User {recipient_id} not found, skipping notification")
                return False
                
            user_data = user.to_dict()
            is_online = user_data.get('isOnline', False)
            
            # Prepare notification content
            title = f"{sender_name}"
            body = "sent you a friend request"
            
            # If user is offline, send push notification
            if not is_online:
                # Check notification preferences
                should_notify = await self._check_notification_preferences(
                    recipient_id, 
                    NotificationType.FRIEND_REQUEST
                )
                
                if should_notify:
                    # Send push notification
                    await self._send_push_notification(
                        recipient_id,
                        title,
                        body,
                        {
                            'senderId': sender_id,
                            'type': 'friend_request'
                        }
                    )
                    
                # Store notification in database
                await self._store_notification(
                    recipient_id,
                    NotificationType.FRIEND_REQUEST,
                    title,
                    body,
                    {
                        'senderId': sender_id
                    }
                )
                
            return True
            
        except Exception as e:
            logger.error(f"Error processing friend request: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def _process_direct_conversation_created(self, event_data: Dict[str, Any]) -> bool:
        """
        Process a direct conversation created notification
        
        Args:
            event_data: The event data containing conversation details
            
        Returns:
            bool: True if processing was successful, False otherwise
        """
        try:
            # Extract necessary data
            conversation_id = event_data.get('conversation_id')
            creator_id = event_data.get('creator_id')
            participants = event_data.get('participants', [])
            initial_message = event_data.get('initial_message')
            
            # Validate required fields
            if not all([conversation_id, creator_id, participants]):
                logger.error(f"Missing required fields in direct conversation data: {event_data}")
                return False
                
            logger.info(f"Processing direct conversation created notification for {conversation_id}")
            
            # Get creator details
            creator_ref = firestore_db.collection('users').document(creator_id)
            creator = creator_ref.get()
            creator_name = creator_id  # Default to creator ID if name not found
            
            if creator.exists:
                creator_data = creator.to_dict()
                creator_name = creator_data.get('name', creator_id)
                
            # Notify all participants except creator
            for participant_id in participants:
                if participant_id == creator_id:
                    continue  # Skip creator
                    
                # Check if user is online
                user_ref = firestore_db.collection('users').document(participant_id)
                user = user_ref.get()
                
                if not user.exists:
                    logger.warning(f"User {participant_id} not found, skipping notification")
                    continue
                    
                user_data = user.to_dict()
                is_online = user_data.get('isOnline', False)
                
                # Prepare notification content
                title = f"{creator_name}"
                body = "started a conversation with you"
                
                if initial_message:
                    body = initial_message[:100] + ('...' if len(initial_message) > 100 else '')
                    
                # If user is offline, send push notification
                if not is_online:
                    # Check notification preferences
                    should_notify = await self._check_notification_preferences(
                        participant_id, 
                        NotificationType.MESSAGE
                    )
                    
                    if should_notify:
                        # Send push notification
                        await self._send_push_notification(
                            participant_id,
                            title,
                            body,
                            {
                                'conversationId': conversation_id,
                                'senderId': creator_id,
                                'type': 'direct_conversation'
                            }
                        )
                        
                    # Store notification in database
                    await self._store_notification(
                        participant_id,
                        NotificationType.MESSAGE,
                        title,
                        body,
                        {
                            'conversationId': conversation_id,
                            'senderId': creator_id
                        }
                    )
                    
            return True
            
        except Exception as e:
            logger.error(f"Error processing direct conversation creation: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def _process_group_conversation_created(self, event_data: Dict[str, Any]) -> bool:
        """
        Process a group conversation created notification
        
        Args:
            event_data: The event data containing conversation details
            
        Returns:
            bool: True if processing was successful, False otherwise
        """
        try:
            # Extract necessary data
            conversation_id = event_data.get('conversation_id')
            creator_id = event_data.get('creator_id')
            participants = event_data.get('participants', [])
            group_name = event_data.get('name', 'a group')
            
            # Validate required fields
            if not all([conversation_id, creator_id, participants, group_name]):
                logger.error(f"Missing required fields in group conversation data: {event_data}")
                return False
                
            logger.info(f"Processing group conversation created notification for {conversation_id}")
            
            # Get creator details
            creator_ref = firestore_db.collection('users').document(creator_id)
            creator = creator_ref.get()
            creator_name = creator_id  # Default to creator ID if name not found
            
            if creator.exists:
                creator_data = creator.to_dict()
                creator_name = creator_data.get('name', creator_id)
                
            # Notify all participants except creator
            for participant_id in participants:
                if participant_id == creator_id:
                    continue  # Skip creator
                    
                # Check if user is online
                user_ref = firestore_db.collection('users').document(participant_id)
                user = user_ref.get()
                
                if not user.exists:
                    logger.warning(f"User {participant_id} not found, skipping notification")
                    continue
                    
                user_data = user.to_dict()
                is_online = user_data.get('isOnline', False)
                
                # Prepare notification content
                title = f"{creator_name}"
                body = f"added you to group {group_name}"
                
                # If user is offline, send push notification
                if not is_online:
                    # Check notification preferences
                    should_notify = await self._check_notification_preferences(
                        participant_id, 
                        NotificationType.GROUP_INVITATION
                    )
                    
                    if should_notify:
                        # Send push notification
                        await self._send_push_notification(
                            participant_id,
                            title,
                            body,
                            {
                                'conversationId': conversation_id,
                                'senderId': creator_id,
                                'type': 'group_conversation'
                            }
                        )
                        
                    # Store notification in database
                    await self._store_notification(
                        participant_id,
                        NotificationType.GROUP_INVITATION,
                        title,
                        body,
                        {
                            'conversationId': conversation_id,
                            'senderId': creator_id
                        }
                    )
                    
            return True
            
        except Exception as e:
            logger.error(f"Error processing group conversation creation: {str(e)}")
            logger.error(traceback.format_exc())
            return False

    async def _check_notification_preferences(self, user_id: str, notification_type: NotificationType) -> bool:
        """
        Check if a user has enabled notifications for this type
        
        Args:
            user_id: The user ID
            notification_type: The type of notification
            
        Returns:
            bool: True if notifications should be sent, False otherwise
        """
        try:
            # Get user's notification preferences
            pref_ref = firestore_db.collection('notification_preferences').document(user_id)
            pref = pref_ref.get()
            
            if pref.exists:
                pref_data = pref.to_dict()
                
                # Check global push setting
                push_enabled = pref_data.get('pushEnabled', True)
                if not push_enabled:
                    logger.info(f"Push notifications disabled for user {user_id}")
                    return False
                    
                # Check mute until time
                mute_until = pref_data.get('muteUntil')
                if mute_until:
                    now = datetime.now(timezone.utc)
                    
                    if isinstance(mute_until, datetime) and now < mute_until:
                        logger.info(f"Notifications muted for user {user_id} until {mute_until}")
                        return False
                    elif hasattr(mute_until, 'datetime') and now < mute_until.datetime():
                        logger.info(f"Notifications muted for user {user_id} until {mute_until.datetime()}")
                        return False
                        
                # Check specific notification type
                if notification_type == NotificationType.MESSAGE:
                    return pref_data.get('messageNotifications', True)
                elif notification_type == NotificationType.GROUP_INVITATION:
                    return pref_data.get('groupNotifications', True)
                elif notification_type == NotificationType.FRIEND_REQUEST:
                    return pref_data.get('friendRequestNotifications', True)
                elif notification_type == NotificationType.SYSTEM:
                    return pref_data.get('systemNotifications', True)
                    
            # Default to enabled if no preferences found
            return True
            
        except Exception as e:
            logger.error(f"Error checking notification preferences for user {user_id}: {str(e)}")
            return True  # Default to True in case of error

    async def _send_push_notification(self, user_id: str, title: str, body: str, data: Dict[str, Any] = None) -> bool:
        """
        Send push notification to a user's devices
        
        Args:
            user_id: The user ID
            title: The notification title
            body: The notification body
            data: Additional data to include with the notification
            
        Returns:
            bool: True if at least one notification was sent successfully, False otherwise
        """
        try:
            logger.info(f"Sending push notification to user {user_id}")
            
            # Get user's device tokens
            tokens_ref = firestore_db.collection('device_tokens')
            query = tokens_ref.where('userId', '==', user_id)
            token_docs = query.stream()
            
            device_tokens = {}
            for token_doc in token_docs:
                token_data = token_doc.to_dict()
                device_type = token_data.get('deviceType')
                token = token_data.get('token')
                
                if device_type and token:
                    if device_type not in device_tokens:
                        device_tokens[device_type] = []
                    device_tokens[device_type].append((token, token_doc.id))
                    
            if not device_tokens:
                logger.info(f"No device tokens found for user {user_id}")
                return False
                
            success = False
            data = data or {}
            
            # Standardize data format for all platforms
            if isinstance(data, dict):
                # Convert all values to strings for FCM compatibility
                data = {k: str(v) if not isinstance(v, str) else v for k, v in data.items()}
            
            # Send notifications through appropriate channels based on device type
            for platform, tokens in device_tokens.items():
                for token_info in tokens:
                    token, doc_id = token_info
                    try:
                        # For iOS and Android, use Firebase Cloud Messaging
                        if platform in ['ios', 'android']:
                            message = messaging.Message(
                                notification=messaging.Notification(
                                    title=title,
                                    body=body
                                ),
                                data=data,
                                token=token
                            )
                            
                            response = messaging.send(message)
                            logger.info(f"Successfully sent FCM message to {platform} device: {response}")
                            success = True
                            
                        # For web, use AWS SNS if available
                        elif platform == 'web' and settings.aws_sns_topic_arn:
                            sns_topic_arn = settings.aws_sns_topic_arn
                            
                            payload = {
                                'default': f"{title}: {body}",
                                'GCM': json.dumps({
                                    'notification': {
                                        'title': title,
                                        'body': body
                                    },
                                    'data': data
                                })
                            }
                            
                            response = self.sns_client.publish(
                                TopicArn=sns_topic_arn,
                                Message=json.dumps(payload),
                                MessageStructure='json'
                            )
                            
                            logger.info(f"Successfully sent SNS message: {response}")
                            success = True
                            
                    except messaging.ApiCallError as fcm_error:
                        logger.error(f"Firebase messaging error: {str(fcm_error)}")
                        
                        # Handle invalid token errors
                        if hasattr(fcm_error, 'code') and fcm_error.code in [
                            'registration-token-not-registered',
                            'invalid-argument',
                            'invalid-registration-token'
                        ]:
                            logger.info(f"Removing invalid token: {token}")
                            await self._remove_invalid_token(doc_id)
                            
                    except Exception as e:
                        logger.error(f"Error sending push notification to {platform} device: {str(e)}")
                        
            return success
            
        except Exception as e:
            logger.error(f"Error in send_push_notification: {str(e)}")
            return False

    async def _remove_invalid_token(self, token_doc_id: str):
        """
        Remove an invalid device token from the database
        
        Args:
            token_doc_id: The document ID of the token to remove
        """
        try:
            token_ref = firestore_db.collection('device_tokens').document(token_doc_id)
            await asyncio.to_thread(token_ref.delete)
            logger.info(f"Removed invalid token with document ID: {token_doc_id}")
        except Exception as e:
            logger.error(f"Error removing invalid token: {str(e)}")

    async def _store_notification(self, user_id: str, type: NotificationType, title: str, body: str, data: Dict[str, Any] = None):
        """
        Store notification in Firestore for retrieval when user comes online
        
        Args:
            user_id: The user ID
            type: The notification type
            title: The notification title
            body: The notification body
            data: Additional data to include with the notification
            
        Returns:
            str: The notification ID if successful, None otherwise
        """
        try:
            notification_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            
            notification_data = {
                'notificationId': notification_id,
                'userId': user_id,
                'type': type.value,
                'title': title,
                'body': body,
                'data': data or {},
                'isRead': False,
                'createdAt': now
            }
            
            # Store in Firestore
            notif_ref = firestore_db.collection('notifications').document(notification_id)
            await asyncio.to_thread(notif_ref.set, notification_data)
            
            # Update user's unread notification count
            user_ref = firestore_db.collection('users').document(user_id)
            transaction = firestore_db.transaction()
            
            @firestore.transactional
            def update_unread_count(transaction, user_ref):
                user_doc = user_ref.get(transaction=transaction)
                if user_doc.exists:
                    user_data = user_doc.to_dict()
                    unread_count = user_data.get('unreadNotifications', 0)
                    transaction.update(user_ref, {'unreadNotifications': unread_count + 1})
            
            try:
                await asyncio.to_thread(update_unread_count, transaction, user_ref)
                logger.info(f"Updated unread count for user {user_id}")
            except Exception as e:
                logger.error(f"Error updating unread count: {str(e)}")
            
            logger.info(f"Stored notification {notification_id} for user {user_id}")
            return notification_id
            
        except Exception as e:
            logger.error(f"Error storing notification: {str(e)}")
            return None
