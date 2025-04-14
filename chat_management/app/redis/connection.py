import redis.asyncio as redis
import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

@lru_cache()
def get_redis_config():
    """
    Get Redis connection parameters from environment variables
    
    Returns:
        dict: Configuration dictionary for Redis connection
    """
    return {
        'host': os.environ.get('REDIS_HOST', 'localhost'),
        'port': int(os.environ.get('REDIS_PORT', 6379)),
        'db': int(os.environ.get('REDIS_DB', 0)),
        'password': os.environ.get('REDIS_PASSWORD', None),
        'ssl': os.environ.get('REDIS_SSL', 'false').lower() == 'true',
        'decode_responses': True
    }

async def get_redis_connection():
    """
    Get an async Redis connection using connection pooling
    
    Returns:
        Redis: Asynchronous Redis client instance
    
    Raises:
        Exception: If Redis connection fails
    """
    try:
        config = get_redis_config()
        connection_pool = redis.ConnectionPool(**config)
        return redis.Redis(connection_pool=connection_pool)
    except Exception as e:
        logger.error(f"Redis connection error: {str(e)}")
        raise
