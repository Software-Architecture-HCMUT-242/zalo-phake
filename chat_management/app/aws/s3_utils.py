import logging
import uuid
from datetime import datetime
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
        # Parse allowed file types from configuration string
        self.allowed_file_types = settings.aws_s3_allowed_file_types.split(',')
        logger.info(f"S3 client initialized with bucket: {settings.aws_s3_bucket_name}")
        
    def is_file_type_allowed(self, content_type: str) -> bool:
        """
        Check if the file type is allowed based on its MIME type.
        
        Args:
            content_type: MIME type of the file
            
        Returns:
            bool: True if file type is allowed, False otherwise
        """
        # If content_type is None or empty, default to octet-stream
        if not content_type:
            content_type = "application/octet-stream"
            
        # If there are no restrictions, allow all types
        if not self.allowed_file_types or '*/*' in self.allowed_file_types:
            return True
            
        # Check if the exact MIME type is allowed
        if content_type in self.allowed_file_types:
            return True
            
        # Check if the MIME type category is allowed (e.g., 'image/*')
        mime_category = content_type.split('/')[0] + '/*'
        if mime_category in self.allowed_file_types:
            return True
            
        return False

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

    def generate_presigned_url(self, object_name: str, expiration: int = None) -> str:
        """
        Generate a presigned URL for an S3 object.

        Args:
            object_name: Name of the object to generate URL for
            expiration: Time in seconds for the URL to remain valid (default: 1 hour)

        Returns:
            str: Presigned URL
        """
        try:
            # Use default expiration from settings if not provided
            if expiration is None:
                expiration = settings.aws_s3_presigned_url_expiration
                
            logger.debug(f"Generating presigned URL for object: {object_name}")
            url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': settings.aws_s3_bucket_name,
                    'Key': object_name
                },
                ExpiresIn=expiration
            )
            
            # Log URL generation (but not the actual URL in production)
            if settings.is_production_environment:
                logger.info(f"Generated presigned URL for {object_name} with expiration {expiration}s")
            else:
                logger.debug(f"Generated URL: {url}")
                
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
