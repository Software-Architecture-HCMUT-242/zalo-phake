import boto3
from botocore.exceptions import ClientError
import json
from .config import settings
import logging

logger = logging.getLogger(__name__)

class SQSClient:
    def __init__(self, **kwargs):
        """
        Initialize SQS client with proper configuration.
        """
        self.sqs = boto3.client(
            'sqs',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            **kwargs
        )
        logger.info(f"SQS client initialized with queue URL: {settings.aws_sqs_queue_url}")

    def send_message(self, queue_url, message_body, delay_seconds=0, message_attributes=None):
        """
        Send a message to an SQS queue with improved error handling and logging.
        """
        try:
            # Convert dict to JSON string if necessary
            if isinstance(message_body, dict):
                message_body = json.dumps(message_body)

            params = {
                'QueueUrl': queue_url,
                'MessageBody': message_body,
                'DelaySeconds': delay_seconds
            }

            # Add message attributes if provided
            if message_attributes:
                params['MessageAttributes'] = message_attributes

            logger.debug(f"Sending message to SQS queue: {queue_url}")
            response = self.sqs.send_message(**params)
            logger.info(f"Message sent to SQS with MessageId: {response.get('MessageId')}")
            return response

        except ClientError as e:
            logger.error(f"Error sending message to SQS: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error sending message to SQS: {e}")
            raise

    def receive_messages(self, queue_url, max_number=10, wait_time_seconds=20, visibility_timeout=30):
        """
        Receive messages from an SQS queue.
        """
        try:
            logger.debug(f"Receiving messages from SQS queue: {queue_url}")
            response = self.sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_number,
                WaitTimeSeconds=wait_time_seconds,
                VisibilityTimeout=visibility_timeout
            )

            messages = response.get('Messages', [])
            logger.info(f"Received {len(messages)} messages from SQS")
            return messages

        except ClientError as e:
            logger.error(f"Error receiving messages from SQS: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error receiving messages from SQS: {e}")
            raise

    def delete_message(self, queue_url, receipt_handle):
        """
        Delete a message from an SQS queue.
        """
        try:
            logger.debug(f"Deleting message from SQS queue: {queue_url}")
            self.sqs.delete_message(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle
            )
            logger.info(f"Message deleted from SQS")

        except ClientError as e:
            logger.error(f"Error deleting message from SQS: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error deleting message from SQS: {e}")
            raise