import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Union

from config import settings
from firebase_client import FirebaseClient
from sqs_client import SQSClient

logger = logging.getLogger(__name__)


class EventProcessor:
    """Processes notification events from SQS queue."""
    
    def __init__(self, firebase_client: FirebaseClient, sqs_client: SQSClient):
        """
        Initialize the event processor.
        
        Args:
            firebase_client: Initialized Firebase client
            sqs_client: Initialized SQS client
        """
        self.firebase = firebase_client
        self.sqs = sqs_client
        logger.info("Event processor initialized")
    
    def process_event(self, message: Dict) -> bool:
        """
        Process an SQS message containing a notification event.
        
        Args:
            message: SQS message dictionary
            
        Returns:
            True if processing was successful, False otherwise
        """
        try:
            # Extract message body
            receipt_handle = message.get('ReceiptHandle')
            
            if not receipt_handle:
                logger.error("Missing receipt handle in SQS message")
                return False
            
            body = message.get('Body', '{}')
            
            # Parse message body
            try:
                event_data = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in message body: {str(e)}")
                return False
            
            # Extract event metadata
            event_id = event_data.get('messageId') or event_data.get('eventId')
            event_type = event_data.get('event') or event_data.get('eventType')
            
            if not event_id:
                event_id = str(uuid.uuid4())
                logger.warning(f"Event ID missing, generated: {event_id}")
            
            if not event_type:
                logger.error("Missing event type in message")
                return False
            
            # Check for retry attempt information
            retry_data = event_data.get('_retry', {})
            current_attempt = retry_data.get('attempt', 1)
            
            # Process based on event type
            logger.info(f"Processing {event_type} event (ID: {event_id}, attempt: {current_attempt})")
            
            # Route to appropriate handler
            success = False
            if event_type == 'new_message':
                success = self._process_new_message(event_data)
            elif event_type == 'group_invitation':
                success = self._process_group_invitation(event_data)
            elif event_type == 'friend_request':
                success = self._process_friend_request(event_data)
            else:
                logger.warning(f"Unknown event type: {event_type}")
                return False
            
            # Handle success/failure
            if success:
                # Delete message from queue on success
                logger.info(f"Successfully processed {event_type} event (ID: {event_id})")
                self.sqs.delete_message(settings.main_queue_url, receipt_handle)
                return True
            else:
                # Send to retry queue on failure
                logger.warning(f"Failed to process {event_type} event (ID: {event_id})")
                self.sqs.send_to_retry_queue(event_data, current_attempt + 1)
                self.sqs.delete_message(settings.main_queue_url, receipt_handle)
                return False
                
        except Exception as e:
            logger.error(f"Error processing event: {str(e)}")
            return False
    
    def _process_new_message(self, event_data: Dict) -> bool:
        """
        Process a new message notification event.
        
        Args:
            event_data: Event data dictionary
            
        Returns:
            True if processing was successful, False otherwise
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
            
            # Get sender info from Firestore
            sender_ref = self.firebase.firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id  # Default to ID if name not found
            
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)
            
            # Track overall success
            overall_success = True
            
            # Process each recipient
            for participant_id in participants:
                if participant_id == sender_id:
                    continue  # Skip the sender
                
                # Check if user is online
                is_online = self.firebase.is_user_online(participant_id)
                
                # If user is offline, consider sending notification
                if not is_online:
                    # Generate unique notification ID
                    notification_id = str(uuid.uuid4())
                    
                    # Store notification in Firestore
                    notification_data = {
                        'conversationId': conversation_id,
                        'messageId': message_id,
                        'senderId': sender_id
                    }
                    
                    # Truncate content if needed
                    display_content = content
                    if len(display_content) > settings.max_notification_content_length:
                        display_content = content[:settings.max_notification_content_length] + '...'
                    
                    # Store in Firestore
                    storage_success = self.firebase.store_notification(
                        notification_id,
                        participant_id,
                        'message',
                        sender_name,
                        display_content,
                        notification_data
                    )
                    
                    # Check notification preferences for push delivery
                    preferences = self.firebase.get_user_preferences(participant_id)
                    should_notify = preferences.get('pushEnabled', True) and preferences.get('messageNotifications', True)
                    
                    # Send push notification if enabled
                    if should_notify:
                        push_result = self.firebase.send_fcm_notification(
                            participant_id,
                            sender_name,
                            display_content,
                            notification_data
                        )
                        
                        # Update overall success
                        if not push_result.get('success'):
                            if push_result.get('status') != 'NO_TOKENS':
                                logger.warning(f"Push notification failed for user {participant_id}")
                                overall_success = overall_success and False
                    
                    # Update overall success based on storage
                    overall_success = overall_success and storage_success
            
            return overall_success
            
        except Exception as e:
            logger.error(f"Error processing new message notification: {str(e)}")
            return False
    
    def _process_group_invitation(self, event_data: Dict) -> bool:
        """
        Process a group invitation notification event.
        
        Args:
            event_data: Event data dictionary
            
        Returns:
            True if processing was successful, False otherwise
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
            
            logger.info(f"Processing group invitation notification for {invitee_id}")
            
            # Get sender info from Firestore
            sender_ref = self.firebase.firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id  # Default to ID if name not found
            
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)
            
            # Check if invitee is online
            is_online = self.firebase.is_user_online(invitee_id)
            
            # Prepare notification content
            title = f"{sender_name}"
            body = f"invited you to join {group_name}"
            notification_data = {
                'conversationId': conversation_id,
                'senderId': sender_id,
                'type': 'group_invitation'
            }
            
            # Generate unique notification ID
            notification_id = str(uuid.uuid4())
            
            # Store notification in Firestore
            storage_success = self.firebase.store_notification(
                notification_id,
                invitee_id,
                'group_invitation',
                title,
                body,
                notification_data
            )
            
            # If user is offline, consider sending push notification
            if not is_online:
                # Check notification preferences
                preferences = self.firebase.get_user_preferences(invitee_id)
                should_notify = preferences.get('pushEnabled', True) and preferences.get('groupNotifications', True)
                
                # Send push notification if enabled
                if should_notify:
                    self.firebase.send_fcm_notification(
                        invitee_id,
                        title,
                        body,
                        notification_data
                    )
            
            return storage_success
            
        except Exception as e:
            logger.error(f"Error processing group invitation notification: {str(e)}")
            return False
    
    def _process_friend_request(self, event_data: Dict) -> bool:
        """
        Process a friend request notification event.
        
        Args:
            event_data: Event data dictionary
            
        Returns:
            True if processing was successful, False otherwise
        """
        try:
            # Extract necessary data
            sender_id = event_data.get('senderId')
            recipient_id = event_data.get('recipientId')
            
            # Validate required fields
            if not all([sender_id, recipient_id]):
                logger.error(f"Missing required fields in friend request data: {event_data}")
                return False
            
            logger.info(f"Processing friend request notification from {sender_id} to {recipient_id}")
            
            # Get sender info from Firestore
            sender_ref = self.firebase.firestore_db.collection('users').document(sender_id)
            sender = sender_ref.get()
            sender_name = sender_id  # Default to ID if name not found
            
            if sender.exists:
                sender_data = sender.to_dict()
                sender_name = sender_data.get('name', sender_id)
            
            # Check if recipient is online
            is_online = self.firebase.is_user_online(recipient_id)
            
            # Prepare notification content
            title = f"{sender_name}"
            body = "sent you a friend request"
            notification_data = {
                'senderId': sender_id,
                'type': 'friend_request'
            }
            
            # Generate unique notification ID
            notification_id = str(uuid.uuid4())
            
            # Store notification in Firestore
            storage_success = self.firebase.store_notification(
                notification_id,
                recipient_id,
                'friend_request',
                title,
                body,
                notification_data
            )
            
            # If user is offline, consider sending push notification
            if not is_online:
                # Check notification preferences
                preferences = self.firebase.get_user_preferences(recipient_id)
                should_notify = preferences.get('pushEnabled', True) and preferences.get('friendRequestNotifications', True)
                
                # Send push notification if enabled
                if should_notify:
                    self.firebase.send_fcm_notification(
                        recipient_id,
                        title,
                        body,
                        notification_data
                    )
            
            return storage_success
            
        except Exception as e:
            logger.error(f"Error processing friend request notification: {str(e)}")
            return False