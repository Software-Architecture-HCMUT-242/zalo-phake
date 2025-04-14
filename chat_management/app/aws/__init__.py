import logging
import os

from .client import SQSClient
from .config import settings

logger = logging.getLogger(__name__)

# Initialize SQS client only if queue URL is configured
sqs_client = None

if settings.aws_sqs_queue_url:
  try:
    sqs_client = SQSClient()
    logger.info(f"SQS client initialized with queue: {settings.aws_sqs_queue_url}")
  except Exception as e:
    logger.error(f"Failed to initialize SQS client: {str(e)}")
    if os.environ.get('ENVIRONMENT') == 'PROD':
      # In production, this is a critical error
      logger.critical("SQS initialization failed in production environment.")
      raise
    else:
      # In development, we can continue without SQS
      logger.warning("Continuing without SQS client in development environment.")
else:
  logger.warning("SQS queue URL not configured, SQS features will be disabled.")