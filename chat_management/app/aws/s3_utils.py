import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional, BinaryIO

import boto3
from botocore.exceptions import ClientError

from .config import settings

logger = logging.getLogger(__name__)


class S3Client:
    def __init__(self, **kwargs):
        """
        Initialize S3 client with proper configuration.
        """
        self.s3 = boto3.client(
            's3',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            **kwargs
        )
        logger.info(f"S3 client initialized with bucket: {settings.aws_s3_bucket_name}")

    async def upload_file(self, file_obj: BinaryIO, object_name: Optional[str] = None, content_type: Optional[str] = None) -> str:
        """
        Upload a file to an S3 bucket with improved error handling and logging.

        Args:
            file_obj: File object to upload
            object_name: S3 object name. If not specified, a UUID is generated
            content_type: Content type of the file

        Returns:
            str: Object key if file was uploaded successfully
        """
        try:
            # Generate a unique object name if not provided
            if object_name is None:
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                object_name = f"files/{timestamp}_{uuid.uuid4()}"

            extra_args = {}
            if content_type:
                extra_args['ContentType'] = content_type

            logger.debug(f"Uploading file to S3 bucket: {settings.aws_s3_bucket_name}, object: {object_name}")
            self.s3.upload_fileobj(
                file_obj, 
                settings.aws_s3_bucket_name, 
                object_name,
                ExtraArgs=extra_args
            )
            logger.info(f"File uploaded to S3: {object_name}")
            return object_name

        except ClientError as e:
            logger.error(f"Error uploading file to S3: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error uploading file to S3: {e}")
            raise

    def generate_presigned_url(self, object_name: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for an S3 object.

        Args:
            object_name: Name of the object to generate URL for
            expiration: Time in seconds for the URL to remain valid (default: 1 hour)

        Returns:
            str: Presigned URL
        """
        try:
            logger.debug(f"Generating presigned URL for object: {object_name}")
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.aws_s3_bucket_name,
                    'Key': object_name
                },
                ExpiresIn=expiration
            )
            return url

        except ClientError as e:
            logger.error(f"Error generating presigned URL: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {e}")
            raise


# Initialize S3 client if bucket name is configured
s3_client = None

if settings.aws_s3_bucket_name:
    try:
        s3_client = S3Client()
        logger.info(f"S3 client initialized with bucket: {settings.aws_s3_bucket_name}")
    except Exception as e:
        logger.error(f"Failed to initialize S3 client: {str(e)}")
        # In production, we should consider this a critical error
        if settings.is_production_environment:
            logger.critical("S3 initialization failed in production environment.")
            raise
        else:
            # In development, we can continue with a warning
            logger.warning("Continuing without S3 client in development environment.")
else:
    logger.warning("S3 bucket name not configured, file upload features will be disabled.")
