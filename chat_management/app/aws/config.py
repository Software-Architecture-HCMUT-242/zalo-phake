from pydantic_settings import BaseSettings

class AWSConfig(BaseSettings):
    aws_access_key_id: str = 'x'
    aws_secret_access_key: str = 'x'
    aws_region: str = 'ap-southeast-1'
    aws_sqs_queue_url: str = 'http://localhost:9324'


settings = AWSConfig()