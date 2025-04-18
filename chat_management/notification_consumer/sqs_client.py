import json
import logging
from typing import Dict, List, Optional, Union

import boto3
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)


class SQSClient:
    """SQS client for the Notification Consumer Service."""
    
    def __init__(self):
        """Initialize SQS client with main, retry, and DLQ queues."""
        self.sqs = boto3.client(
            'sqs',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        logger.info("SQS client initialized")
    
    def receive_messages(self, 
                        queue_url: str, 
                        max_messages: int = None, 
                        wait_time: int = None, 
                        visibility_timeout: int = None) -> List[Dict]:
        """
        Receive messages from an SQS queue.
        
        Args:
            queue_url: The SQS queue URL
            max_messages: Maximum number of messages to receive (1-10)
            wait_time: Long polling wait time in seconds (0-20)
            visibility_timeout: Visibility timeout in seconds
            
        Returns:
            List of message dictionaries
        """
        try:
            # Use defaults from settings if not specified
            max_messages = max_messages or settings.sqs_max_messages
            wait_time = wait_time or settings.sqs_wait_time
            visibility_timeout = visibility_timeout or settings.sqs_visibility_timeout
            
            # Receive messages
            logger.debug(f"Receiving messages from {queue_url}")
            response = self.sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time,
                VisibilityTimeout=visibility_timeout,
                AttributeNames=['All'],
                MessageAttributeNames=['All']
            )
            
            messages = response.get('Messages', [])
            logger.info(f"Received {len(messages)} messages from {queue_url}")
            return messages
            
        except ClientError as e:
            logger.error(f"Error receiving messages from {queue_url}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error receiving messages: {str(e)}")
            return []
    
    def delete_message(self, queue_url: str, receipt_handle: str) -> bool:
        """
        Delete a message from an SQS queue.
        
        Args:
            queue_url: The SQS queue URL
            receipt_handle: The receipt handle of the message to delete
            
        Returns:
            True if successful, False otherwise
        """
        try:
            logger.debug(f"Deleting message from {queue_url}")
            self.sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.debug("Message deleted successfully")
            return True
            
        except ClientError as e:
            logger.error(f"Error deleting message: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting message: {str(e)}")
            return False
    
    def send_to_queue(self, 
                     queue_url: str, 
                     message_body: Union[str, Dict], 
                     delay_seconds: int = 0, 
                     message_attributes: Optional[Dict] = None,
                     message_group_id: Optional[str] = None) -> Optional[str]:
        """
        Send a message to an SQS queue.
        
        Args:
            queue_url: The SQS queue URL
            message_body: Message body (string or dictionary)
            delay_seconds: Delay before message becomes visible
            message_attributes: Optional message attributes
            message_group_id: Optional message group ID for FIFO queues
            
        Returns:
            Message ID if successful, None otherwise
        """
        try:
            # Convert dict to JSON string if necessary
            if isinstance(message_body, dict):
                message_body = json.dumps(message_body)
            
            # Prepare send parameters
            params = {
                'QueueUrl': queue_url,
                'MessageBody': message_body,
                'DelaySeconds': delay_seconds
            }
            
            # Add message attributes if provided
            if message_attributes:
                params['MessageAttributes'] = message_attributes
            
            # Add FIFO queue parameters if message_group_id is provided
            if message_group_id:
                # Extract message ID from body for deduplication
                try:
                    body_dict = json.loads(message_body)
                    message_deduplication_id = body_dict.get('messageId', f"{message_group_id}-{hash(message_body)}")
                    
                    params['MessageGroupId'] = message_group_id
                    params['MessageDeduplicationId'] = message_deduplication_id
                except (json.JSONDecodeError, TypeError):
                    # If message_body isn't valid JSON, use a hash of the body
                    params['MessageGroupId'] = message_group_id
                    params['MessageDeduplicationId'] = f"{message_group_id}-{hash(message_body)}"
            
            # Send message
            logger.debug(f"Sending message to {queue_url}")
            response = self.sqs.send_message(**params)
            message_id = response.get('MessageId')
            logger.info(f"Message sent to {queue_url} with ID: {message_id}")
            
            return message_id
            
        except ClientError as e:
            logger.error(f"Error sending message to {queue_url}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error sending message: {str(e)}")
            return None
    
    def send_to_retry_queue(self, 
                          message_body: Union[str, Dict], 
                          attempt: int,
                          max_attempts: int = None) -> Optional[str]:
        """
        Send a message to the retry queue with exponential backoff delay.
        
        Args:
            message_body: Message body (string or dictionary)
            attempt: Current retry attempt number
            max_attempts: Maximum number of retry attempts
            
        Returns:
            Message ID if successful, None otherwise
        """
        max_attempts = max_attempts or settings.max_retry_attempts
        
        # Check if max retries exceeded
        if attempt >= max_attempts:
            logger.warning(f"Max retry attempts ({max_attempts}) exceeded, sending to DLQ")
            return self.send_to_dlq(message_body)
        
        # Calculate exponential backoff delay
        delay = min(
            settings.initial_backoff_seconds * (settings.backoff_factor ** (attempt - 1)),
            900  # SQS maximum delay is 15 minutes (900 seconds)
        )
        
        # Update retry metadata in message
        if isinstance(message_body, str):
            try:
                message_dict = json.loads(message_body)
                message_dict['_retry'] = {
                    'attempt': attempt,
                    'maxAttempts': max_attempts
                }
                message_body = json.dumps(message_dict)
            except json.JSONDecodeError:
                # If not JSON, pass through as-is
                pass
        elif isinstance(message_body, dict):
            message_body['_retry'] = {
                'attempt': attempt,
                'maxAttempts': max_attempts
            }
        
        # Send to retry queue
        logger.info(f"Sending message to retry queue with delay {delay}s (attempt {attempt}/{max_attempts})")
        return self.send_to_queue(
            queue_url=settings.retry_queue_url,
            message_body=message_body,
            delay_seconds=int(delay)
        )
    
    def send_to_dlq(self, message_body: Union[str, Dict]) -> Optional[str]:
        """
        Send a message to the dead letter queue.
        
        Args:
            message_body: Message body (string or dictionary)
            
        Returns:
            Message ID if successful, None otherwise
        """
        logger.warning("Sending message to dead letter queue")
        return self.send_to_queue(
            queue_url=settings.dlq_url,
            message_body=message_body
        )