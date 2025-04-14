import json
import logging
import os
from typing import Dict, Any

import redis

logger = logging.getLogger(__name__)

class RedisClient:
    """
    Redis client for Pub/Sub and caching
    """
    def __init__(self):
        """
        Initialize Redis client with connection settings from environment variables
        """
        # Get Redis configuration from environment variables
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = os.getenv("REDIS_PASSWORD", None)
        redis_db = int(os.getenv("REDIS_DB", "0"))

        try:
            # Create Redis client
            self.redis = redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                db=redis_db,
                decode_responses=True  # Automatically decode bytes to str
            )
            logger.info(f"Redis client initialized with host={redis_host}, port={redis_port}")
            
            # Test connection
            self.redis.ping()
            logger.info("Successfully connected to Redis")
        except redis.RedisError as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            # Initialize with None so we can handle the absence of Redis gracefully
            self.redis = None

    def is_connected(self) -> bool:
        """
        Check if Redis connection is active
        """
        if not self.redis:
            return False
        
        try:
            return self.redis.ping()
        except redis.RedisError:
            return False

    async def publish(self, channel: str, data: Dict[str, Any]) -> bool:
        """
        Publish a message to a Redis channel
        
        Args:
            channel: The channel to publish to
            data: The data to publish (will be JSON serialized)
            
        Returns:
            bool: True if successful, False otherwise
        """
        if not self.is_connected():
            logger.warning(f"Cannot publish to {channel}: Redis not connected")
            return False
        
        try:
            # Convert dict to JSON string
            json_data = json.dumps(data)
            
            # Publish to the channel
            result = self.redis.publish(channel, json_data)
            
            if result > 0:
                logger.debug(f"Published message to {channel}, received by {result} subscribers")
                return True
            else:
                logger.debug(f"Published message to {channel}, but no subscribers received it")
                return True  # Still successful even if no subscribers
                
        except (redis.RedisError, TypeError, ValueError) as e:
            logger.error(f"Error publishing to {channel}: {str(e)}")
            return False

# Singleton instance
redis_client = RedisClient()
