import redis.asyncio as redis
import os
import logging
import asyncio
from functools import lru_cache

logger = logging.getLogger(__name__)


def get_redis_config():
    """
    Get Redis connection parameters from environment variables

    Returns:
        dict: Configuration dictionary for Redis connection
    """
    conf = {
        'host': os.environ.get('REDIS_HOST', '127.0.0.1'),
        'port': int(os.environ.get('REDIS_PORT', 6379)),
        'db': int(os.environ.get('REDIS_DB', 0)),
        'password': os.environ.get('REDIS_PASSWORD', None),
        'decode_responses': True,
        'username': os.environ.get('REDIS_USERNAME', None),
    }
    if os.environ.get('REDIS_SSL', 'false').lower() == 'true':
        conf['connection_class'] = redis.SSLConnection
    return conf

@lru_cache()
def get_redis_config_cache():
    return get_redis_config()

# Global connection pool for reuse
_connection_pool = None

async def get_redis_connection():
    """
    Get an async Redis connection using connection pooling
    
    Returns:
        Redis: Asynchronous Redis client instance
    
    Raises:
        Exception: If Redis connection fails
    """
    global _connection_pool
    
    try:
        if _connection_pool is None:
            config = get_redis_config_cache()
            _connection_pool = redis.ConnectionPool(**config)
            logger.info("Created new Redis connection pool")
            
        # Create a new connection from the pool
        redis_client = redis.Redis(connection_pool=_connection_pool)
        
        # Test the connection
        await redis_client.ping()
        
        return redis_client
    except Exception as e:
        logger.error(f"Redis connection error: {str(e)}")
        # Reset the connection pool on error to force recreation on next attempt
        _connection_pool = None
        raise

class RedisConnectionFactory:
    """Factory class for creating Redis connections"""
    
    @staticmethod
    async def create_async_client() -> redis.Redis:
        """Create and return a Redis async client"""
        return await get_redis_connection()
