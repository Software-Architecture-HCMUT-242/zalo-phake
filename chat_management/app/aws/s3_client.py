"""
S3 client for handling media uploads (images, videos, audio) in the chat management service
"""
import logging
import boto3
from botocore.exceptions import ClientError
from .config import settings
import uuid
import asyncio
from datetime import datetime, timedelta
import hashlib
import json

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
        self.bucket_name = settings.aws_s3_bucket_name
        logger.info(f"S3 client initialized with bucket: {self.bucket_name}")
    
    def generate_presigned_url(self, user_id: str, conversation_id: str, content_type: str = 'image/jpeg', expiration=3600):
        """
        Generate a presigned URL for uploading media (image, video, audio) directly to S3.
        
        Args:
            user_id: The ID of the user uploading the media
            conversation_id: The ID of the conversation the media belongs to
            content_type: The MIME type of the media
            expiration: URL expiration time in seconds
            
        Returns:
            dict: Contains the presigned URL and the object key
        """
        try:
            # Generate a unique file key using timestamp and UUID
            timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
            file_uuid = str(uuid.uuid4())
            extension = self._get_extension_from_content_type(content_type)
            
            # Determine the media folder based on content type
            media_folder = "images"
            if content_type.startswith("video/"):
                media_folder = "videos"
            elif content_type.startswith("audio/"):
                media_folder = "audios"
            
            # Create object key in format: conversations/{conv_id}/{media_folder}/{user_id}/{timestamp}-{uuid}.ext
            # This organizes media by conversation and type for better access control and cleanup
            object_key = f"conversations/{conversation_id}/{media_folder}/{user_id}/{timestamp}-{file_uuid}{extension}"
            
            # Generate the presigned URL for upload
            presigned_url = self.s3.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_key,
                    'ContentType': content_type,
                    # Store metadata about the uploader and conversation for access control
                    'Metadata': {
                        'conversation-id': conversation_id,
                        'uploader-id': user_id,
                        'upload-time': timestamp
                    }
                },
                ExpiresIn=expiration
            )
            
            logger.info(f"Generated presigned URL for user {user_id} with key {object_key}")
            
            # Generate a signed URL for authorized access with proper token-based verification
            access_url = self._generate_access_url(object_key, conversation_id)
            
            return {
                'presigned_url': presigned_url,
                'object_key': object_key,
                'url': access_url,
                'expires_at': (datetime.utcnow() + timedelta(seconds=expiration)).isoformat()
            }
            
        except ClientError as e:
            logger.error(f"Error generating presigned URL: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error generating presigned URL: {e}")
            raise
    
    def check_object_exists(self, object_key):
        """
        Check if an object exists in the S3 bucket.
        
        Args:
            object_key: The key of the object to check
            
        Returns:
            bool: True if the object exists, False otherwise
        """
        try:
            self.s3.head_object(Bucket=self.bucket_name, Key=object_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                logger.error(f"Error checking if object exists: {e}")
                raise
        except Exception as e:
            logger.error(f"Unexpected error checking if object exists: {e}")
            raise
    
    def get_object_metadata(self, object_key):
        """
        Get metadata for an object in the S3 bucket.
        
        Args:
            object_key: The key of the object
            
        Returns:
            dict: The object metadata or None if not found
        """
        try:
            response = self.s3.head_object(Bucket=self.bucket_name, Key=object_key)
            return {
                'content_type': response.get('ContentType'),
                'size_bytes': response.get('ContentLength'),
                'last_modified': response.get('LastModified'),
                'etag': response.get('ETag'),
                'metadata': response.get('Metadata', {})
            }
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return None
            else:
                logger.error(f"Error getting object metadata: {e}")
                raise
        except Exception as e:
            logger.error(f"Unexpected error getting object metadata: {e}")
            raise
    
    async def delete_object(self, object_key):
        """
        Delete an object from the S3 bucket.
        
        Args:
            object_key: The key of the object to delete
            
        Returns:
            bool: True if the object was deleted, False otherwise
        """
        try:
            await asyncio.to_thread(
                self.s3.delete_object,
                Bucket=self.bucket_name,
                Key=object_key
            )
            logger.info(f"Deleted object {object_key} from bucket {self.bucket_name}")
            return True
        except ClientError as e:
            logger.error(f"Error deleting object {object_key}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error deleting object {object_key}: {e}")
            return False
    
    def generate_signed_url(self, object_key, conversation_id, user_id, expiration=3600):
        """
        Generate a signed URL for viewing media (image, video, audio), with authorization embedded in the URL.
        
        Args:
            object_key: The key of the object in S3
            conversation_id: The conversation ID (for auth verification)
            user_id: The user ID requesting access
            expiration: URL expiration time in seconds
            
        Returns:
            str: Signed URL for accessing the media
        """
        try:
            # Generate a signed URL with embedded conversation ID for server-side verification
            signed_url = self.s3.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket_name,
                    'Key': object_key,
                    # Add a query string parameter for authentication in our API gateway/proxy
                    'ResponseContentDisposition': f'inline; conversation={conversation_id}'
                },
                ExpiresIn=expiration
            )
            
            # Append additional auth token for our proxy verification
            auth_token = self._generate_auth_token(object_key, conversation_id, user_id)
            signed_url = f"{signed_url}&auth={auth_token}"
            
            logger.info(f"Generated signed URL for object {object_key} for user {user_id}")
            return signed_url
            
        except ClientError as e:
            logger.error(f"Error generating signed URL: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error generating signed URL: {e}")
            raise
    
    def _generate_access_url(self, object_key, conversation_id):
        """
        Generate a URL for accessing media through our proxy service which performs auth.
        
        Args:
            object_key: The key of the object in S3
            conversation_id: The conversation ID
            
        Returns:
            str: URL for accessing the media through our proxy
        """
        # Use the proxy URL format that will handle authorization
        # First try to use media_proxy_base_url if available, otherwise fall back to image_proxy_base_url
        proxy_base_url = getattr(settings, 'media_proxy_base_url', settings.image_proxy_base_url)
        
        # Format is: {proxy_base_url}/{conversation_id}/{object_key}
        # The proxy will handle authorization by checking if the user is in the conversation
        encoded_key = object_key.replace('/', '%2F')
        return f"{proxy_base_url}/{conversation_id}/{encoded_key}"
    
    def _generate_auth_token(self, object_key, conversation_id, user_id):
        """
        Generate an auth token for validating media access requests.
        
        Args:
            object_key: The key of the object in S3
            conversation_id: The conversation ID
            user_id: The user ID requesting access
            
        Returns:
            str: Authentication token
        """
        # Create a token using a keyed hash with our secret key
        data = f"{object_key}:{conversation_id}:{user_id}"
        # Try media_auth_secret first, fall back to image_auth_secret if not available
        secret = getattr(settings, 'media_auth_secret', settings.image_auth_secret)
        
        # Use HMAC for secure token generation
        hash_obj = hashlib.sha256(f"{data}:{secret}".encode())
        return hash_obj.hexdigest()
    
    def _get_extension_from_content_type(self, content_type):
        """
        Get the file extension based on MIME type.
        
        Args:
            content_type: The MIME type
            
        Returns:
            str: The file extension including the dot
        """
        # Map of common content types to extensions
        content_type_map = {
            # Images
            'image/jpeg': '.jpg',
            'image/jpg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp',
            'image/svg+xml': '.svg',
            'image/bmp': '.bmp',
            'image/tiff': '.tiff',
            
            # Videos
            'video/mp4': '.mp4',
            'video/mpeg': '.mpg',
            'video/quicktime': '.mov',
            'video/x-msvideo': '.avi',
            'video/webm': '.webm',
            'video/3gpp': '.3gp',
            'video/3gpp2': '.3g2',
            'video/x-matroska': '.mkv',
            
            # Audio
            'audio/mpeg': '.mp3',
            'audio/mp4': '.m4a',
            'audio/wav': '.wav',
            'audio/webm': '.weba',
            'audio/aac': '.aac',
            'audio/ogg': '.ogg',
            'audio/flac': '.flac',
            'audio/x-ms-wma': '.wma'
        }
        
        lowercase_type = content_type.lower()
        
        # Default extensions based on media type
        if lowercase_type.startswith('image/'):
            return content_type_map.get(lowercase_type, '.jpg')
        elif lowercase_type.startswith('video/'):
            return content_type_map.get(lowercase_type, '.mp4')
        elif lowercase_type.startswith('audio/'):
            return content_type_map.get(lowercase_type, '.mp3')
        else:
            return '.bin'  # Generic binary extension as fallback
