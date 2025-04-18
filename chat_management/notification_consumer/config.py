import os
from typing import List, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration settings for the Notification Consumer Service"""
    
    # Application settings
    service_name: str = "notification-consumer"
    log_level: str = "INFO"
    environment: str = "dev"
    
    # AWS SQS settings
    aws_region: str = "ap-southeast-1"
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None
    
    # SQS Queue URLs
    main_queue_url: str = "http://localhost:9324/queue/zalo-phake-notifications"
    retry_queue_url: str = "http://localhost:9324/queue/zalo-phake-notifications-retry"
    dlq_url: str = "http://localhost:9324/queue/zalo-phake-notifications-dlq"
    
    # SQS Processing settings
    sqs_max_messages: int = 10
    sqs_visibility_timeout: int = 60  # seconds
    sqs_wait_time: int = 20  # seconds
    
    # Retry settings
    max_retry_attempts: int = 5
    backoff_factor: int = 2  # for exponential backoff
    initial_backoff_seconds: int = 30
    
    # Firebase settings
    firebase_secret: Optional[str] = None
    firebase_db_url: str = "https://zalophake-bf746-default-rtdb.firebaseio.com/"
    
    # FCM batching settings
    fcm_batch_size: int = 500  # FCM allows up to 500 tokens per multicast request
    
    # Notification processing settings
    max_notification_content_length: int = 100  # max length for notification content

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# Create settings instance
settings = Settings()