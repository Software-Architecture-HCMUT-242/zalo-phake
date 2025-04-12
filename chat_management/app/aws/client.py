import boto3
from botocore.exceptions import ClientError
import json
from .config import settings

class SQSClient:
    def __init__(self, **kwargs):
        """
        Initialize SQS client.
        
        Args:
            region_name (str): AWS region name
            aws_access_key_id (str, optional): AWS access key
            aws_secret_access_key (str, optional): AWS secret key
        """
        
        self.sqs = boto3.client(
            'sqs',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            **kwargs
        )
    
    def send_message(self, queue_url, message_body, delay_seconds=0, message_attributes=None):
        """
        Send a message to an SQS queue.
        
        Args:
            queue_url (str): The URL of the SQS queue
            message_body (str/dict): The message to send (will be converted to JSON if dict)
            delay_seconds (int): The time in seconds to delay delivery of the message
            message_attributes (dict, optional): Message attributes
            
        Returns:
            dict: Response from SQS containing MessageId and MD5OfMessageBody
            
        Raises:
            ClientError: If message couldn't be sent
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
                
            response = self.sqs.send_message(**params)
            return response
            
        except ClientError as e:
            print(f"Error sending message to SQS: {e}")
            raise