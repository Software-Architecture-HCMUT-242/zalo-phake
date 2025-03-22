from pydantic_settings import BaseSettings

class AWSConfig(BaseSettings):
    aws_access_key_id: str
    aws_secret_access_key: str
    aws_region: str
    aws_sqs_queue_url: str


settings = AWSConfig()