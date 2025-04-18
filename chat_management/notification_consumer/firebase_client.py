import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import firebase_admin
from firebase_admin import credentials, firestore, messaging
from firebase_admin.exceptions import FirebaseError

from config import settings

logger = logging.getLogger(__name__)


class FirebaseClient:
    """Firebase client for the Notification Consumer Service."""
    
    # Firebase error codes that indicate an invalid token
    INVALID_TOKEN_CODES = [
        "registration-token-not-registered",
        "invalid-argument",
        "invalid-registration-token",
    ]
    
    def __init__(self):
        """Initialize Firebase client with Firestore and FCM capabilities."""
        self.app = None
        self.firestore_db = None
        self.initialized = False
        self.initialize()
        
    def initialize(self) -> None:
        """Initialize Firebase Admin SDK."""
        if self.initialized:
            return
            
        try:
            # Get Firebase credentials from environment variable
            cert_json = settings.firebase_secret
            if not cert_json:
                logger.error("Firebase secret not found in environment variables")
                raise ValueError("Firebase secret not configured")
                
            # Parse credentials JSON
            cert_dict = json.loads(cert_json)
            if isinstance(cert_dict, str):
                cert_dict = json.loads(cert_dict)
                
            # Initialize Firebase app
            cred = credentials.Certificate(cert_dict)
            self.app = firebase_admin.initialize_app(
                credential=cred,
                options={"databaseURL": settings.firebase_db_url}
            )
            
            # Initialize Firestore client
            self.firestore_db = firestore.client(self.app)
            self.initialized = True
            logger.info("Firebase client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Firebase: {str(e)}")
            raise
    
    def get_user_preferences(self, user_id: str) -> Dict:
        """
        Get user notification preferences from Firestore.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Dict containing user preferences
        """
        try:
            pref_ref = self.firestore_db.collection('notification_preferences').document(user_id)
            pref = pref_ref.get()
            
            if pref.exists:
                return pref.to_dict()
            
            return {
                'pushEnabled': True,
                'messageNotifications': True,
                'groupNotifications': True, 
                'friendRequestNotifications': True,
                'systemNotifications': True
            }
        
        except Exception as e:
            logger.error(f"Error fetching user preferences for {user_id}: {str(e)}")
            # Default to enabling all notifications on error
            return {
                'pushEnabled': True,
                'messageNotifications': True,
                'groupNotifications': True, 
                'friendRequestNotifications': True,
                'systemNotifications': True
            }
    
    def get_user_device_tokens(self, user_id: str) -> Dict[str, List[Tuple[str, str]]]:
        """
        Get a user's device tokens from Firestore.
        
        Args:
            user_id: The user's ID
            
        Returns:
            Dict mapping device types to lists of (token, doc_id) tuples
        """
        device_tokens = {}
        
        try:
            tokens_ref = self.firestore_db.collection('device_tokens')
            query = tokens_ref.where('userId', '==', user_id)
            tokens = query.stream()
            
            for token_doc in tokens:
                token_data = token_doc.to_dict()
                device_type = token_data.get('deviceType')
                token = token_data.get('token')
                
                if device_type and token:
                    if device_type not in device_tokens:
                        device_tokens[device_type] = []
                    device_tokens[device_type].append((token, token_doc.id))
            
            return device_tokens
            
        except Exception as e:
            logger.error(f"Error fetching device tokens for user {user_id}: {str(e)}")
            return {}
    
    def invalidate_token(self, token_doc_id: str) -> bool:
        """
        Remove an invalid device token from Firestore.
        
        Args:
            token_doc_id: Document ID of the token to remove
            
        Returns:
            True if successful, False otherwise
        """
        try:
            self.firestore_db.collection('device_tokens').document(token_doc_id).delete()
            logger.info(f"Removed invalid token: {token_doc_id}")
            return True
        except Exception as e:
            logger.error(f"Error removing invalid token {token_doc_id}: {str(e)}")
            return False
    
    def store_notification(self, 
                          notification_id: str,
                          user_id: str,
                          notification_type: str,
                          title: str,
                          body: str,
                          data: Optional[Dict] = None) -> bool:
        """
        Store a notification in Firestore.
        
        Args:
            notification_id: Unique ID for the notification
            user_id: The recipient's user ID
            notification_type: Type of notification (message, group_invitation, etc.)
            title: Notification title
            body: Notification body/content
            data: Additional notification data
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from datetime import datetime, timezone
            
            notification_data = {
                'notificationId': notification_id,
                'userId': user_id,
                'type': notification_type,
                'title': title,
                'body': body,
                'data': data or {},
                'isRead': False,
                'createdAt': datetime.now(timezone.utc)
            }
            
            # Store in Firestore
            self.firestore_db.collection('notifications').document(notification_id).set(notification_data)
            
            # Update user's unread notification count
            user_ref = self.firestore_db.collection('users').document(user_id)
            user = user_ref.get()
            
            if user.exists:
                transaction = self.firestore_db.transaction()
                
                @firestore.transactional
                def update_unread_count(transaction, user_ref):
                    user_doc = user_ref.get(transaction=transaction)
                    user_data = user_doc.to_dict()
                    unread_count = user_data.get('unreadNotifications', 0)
                    transaction.update(user_ref, {'unreadNotifications': unread_count + 1})
                
                update_unread_count(transaction, user_ref)
                
            logger.info(f"Stored notification {notification_id} for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error storing notification for user {user_id}: {str(e)}")
            return False
    
    def send_fcm_notification(self, 
                             user_id: str,
                             title: str,
                             body: str,
                             data: Optional[Dict] = None) -> Dict:
        """
        Send Firebase Cloud Messaging (FCM) notification to a user's devices.
        
        Args:
            user_id: The recipient's user ID
            title: Notification title
            body: Notification body/content
            data: Additional notification data
            
        Returns:
            Dict with status information
        """
        results = {
            'success': False,
            'platforms': {},
            'tokens_processed': 0,
            'tokens_succeeded': 0,
            'tokens_failed': 0,
            'invalid_tokens_removed': 0
        }
        
        try:
            # Get user's device tokens
            device_tokens = self.get_user_device_tokens(user_id)
            
            if not device_tokens:
                logger.info(f"No device tokens found for user {user_id}")
                results['status'] = 'NO_TOKENS'
                return results
            
            # Process each platform
            for platform, tokens in device_tokens.items():
                platform_results = {
                    'tokens_count': len(tokens),
                    'success_count': 0,
                    'failure_count': 0,
                    'invalid_tokens': 0
                }
                
                # Skip empty token lists
                if not tokens:
                    continue
                
                # Extract just the tokens (without doc IDs) for FCM
                token_values = [t[0] for t in tokens]
                results['tokens_processed'] += len(token_values)
                
                # FCM for iOS and Android
                if platform in ['ios', 'android']:
                    # Batch tokens (max 500 per request)
                    for i in range(0, len(token_values), settings.fcm_batch_size):
                        batch = token_values[i:i+settings.fcm_batch_size]
                        batch_doc_ids = [t[1] for t in tokens[i:i+settings.fcm_batch_size]]
                        
                        try:
                            # Create notification message
                            message = messaging.MulticastMessage(
                                notification=messaging.Notification(
                                    title=title,
                                    body=body
                                ),
                                data=data or {},
                                tokens=batch
                            )
                            
                            # Send batch
                            batch_response = messaging.send_multicast(message)
                            
                            # Process results
                            platform_results['success_count'] += batch_response.success_count
                            platform_results['failure_count'] += batch_response.failure_count
                            results['tokens_succeeded'] += batch_response.success_count
                            results['tokens_failed'] += batch_response.failure_count
                            
                            # Handle failures - check for invalid tokens
                            if batch_response.failure_count > 0:
                                for idx, resp in enumerate(batch_response.responses):
                                    if not resp.success:
                                        error = resp.exception
                                        if error and hasattr(error, 'code') and error.code in self.INVALID_TOKEN_CODES:
                                            # Invalid token - remove it
                                            self.invalidate_token(batch_doc_ids[idx])
                                            platform_results['invalid_tokens'] += 1
                                            results['invalid_tokens_removed'] += 1
                            
                        except FirebaseError as e:
                            logger.error(f"Firebase error sending to {platform}: {str(e)}")
                            platform_results['failure_count'] += len(batch)
                            results['tokens_failed'] += len(batch)
                
                # Store platform results
                results['platforms'][platform] = platform_results
            
            # Overall success if at least one notification was sent
            results['success'] = results['tokens_succeeded'] > 0
            
            return results
            
        except Exception as e:
            logger.error(f"Error sending FCM notifications to user {user_id}: {str(e)}")
            results['error'] = str(e)
            return results
    
    def is_user_online(self, user_id: str) -> bool:
        """
        Check if a user is currently online.
        
        Args:
            user_id: The user's ID
            
        Returns:
            True if user is online, False otherwise
        """
        try:
            user_ref = self.firestore_db.collection('users').document(user_id)
            user = user_ref.get()
            
            if user.exists:
                user_data = user.to_dict()
                return user_data.get('isOnline', False)
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking online status for user {user_id}: {str(e)}")
            return False