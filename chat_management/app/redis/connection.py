import redis.asyncio as redis
import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)


def get_redis_config():
    """
    Get Redis connection parameters from environment variables

    Returns:
        dict: Configuration dictionary for Redis connection
    """
    conf = {
        'host': os.environ.get('REDIS_HOST', 'localhost'),
        'port': int(os.environ.get('REDIS_PORT', 6379)),
        'db': int(os.environ.get('REDIS_DB', 0)),
        'password': os.environ.get('REDIS_PASSWORD', "123456789"),
        'decode_responses': True,
        'socket_timeout': 5,
        'username': os.environ.get('REDIS_USERNAME', 'default'),
    }
    if os.environ.get('REDIS_SSL', 'false').lower() == 'true':
        conf['connection_class'] = redis.SSLConnection
    return conf

@lru_cache()
def get_redis_config_cache():
    return get_redis_config()

async def get_redis_connection():
    """
    Get an async Redis connection using connection pooling
    
    Returns:
        Redis: Asynchronous Redis client instance
    
    Raises:
        Exception: If Redis connection fails
    """
    try:
        config = get_redis_config_cache()
        connection_pool = redis.ConnectionPool(**config)
        return redis.Redis(connection_pool=connection_pool)
    except Exception as e:
        logger.error(f"Redis connection error: {str(e)}")
        raise
