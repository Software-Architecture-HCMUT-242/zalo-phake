import logging
import os

from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

class AWSConfig(BaseSettings):
    """
    AWS Configuration settings for the application.

    These settings can be overridden by environment variables with the same name.
    """
    aws_access_key_id: str = os.environ.get('AWS_ACCESS_KEY_ID', '')
    aws_secret_access_key: str = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
    aws_region: str = os.environ.get('AWS_REGION', 'ap-southeast-1')

    # SQS Configuration
    aws_sqs_queue_url: str = os.environ.get('SQS_URL', 'http://localhost:9324/queue/zalo-phake-notifications')
    aws_sqs_message_group_id: str = os.environ.get('SQS_MESSAGE_GROUP_ID', 'zalo-phake')
    aws_sqs_max_message_size: int = int(os.environ.get('SQS_MAX_MESSAGE_SIZE', '256000'))  # 256KB

    # Push Notification Configuration is now handled by the notification_consumer service using Firebase Cloud Messaging (FCM) only

    # Lambda Configuration
    aws_lambda_function_name: str = os.environ.get('LAMBDA_FUNCTION_NAME', 'zalo-phake-notification-processor')

    def __init__(self, **kwargs):
        """Initialize the AWS configuration and validate settings."""
        super().__init__(**kwargs)
        self._validate_settings()

    def _validate_settings(self):
        """Validate that required AWS settings are provided."""
        if not self.aws_sqs_queue_url:
            logger.warning("SQS queue URL is not set. SQS features will be disabled.")

        # SNS has been replaced with Firebase Cloud Messaging (FCM) for all push notifications

        # Load credentials from environment if not set
        if not self.aws_access_key_id and 'AWS_ACCESS_KEY_ID' in os.environ:
            self.aws_access_key_id = os.environ['AWS_ACCESS_KEY_ID']

        if not self.aws_secret_access_key and 'AWS_SECRET_ACCESS_KEY' in os.environ:
            self.aws_secret_access_key = os.environ['AWS_SECRET_ACCESS_KEY']

        # Check if we have credentials in environment
        has_env_credentials = 'AWS_ACCESS_KEY_ID' in os.environ and 'AWS_SECRET_ACCESS_KEY' in os.environ

        # In development mode, we can use local SQS without credentials
        if not (self.aws_access_key_id and self.aws_secret_access_key) and not has_env_credentials:
            if os.environ.get('ENVIRONMENT') == 'PROD':
                logger.warning("AWS credentials not set in production environment.")
            else:
                logger.info("AWS credentials not set, will use local services or instance profiles.")

# Create a singleton instance of the config
settings = AWSConfig()