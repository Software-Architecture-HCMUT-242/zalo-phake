import logging
import os

from .client import SQSClient
from .config import settings
from .s3_utils import S3Client

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

# Initialize S3 client only if bucket name is configured
s3_client = None

if settings.aws_s3_bucket_name:
  try:
    s3_client = S3Client()
    logger.info(f"S3 client initialized with bucket: {settings.aws_s3_bucket_name}")
  except Exception as e:
    logger.error(f"Failed to initialize S3 client: {str(e)}")
    if os.environ.get('ENVIRONMENT') == 'PROD':
      # In production, this is a critical error
      logger.critical("S3 initialization failed in production environment.")
      raise
    else:
      # In development, we can continue without S3
      logger.warning("Continuing without S3 client in development environment.")
else:
  logger.warning("S3 bucket name not configured, file upload features will be disabled.")