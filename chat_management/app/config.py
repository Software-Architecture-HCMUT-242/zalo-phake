from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    path_prefix: str = ''
    fastapi_secret_key: str = '1234567890'
    
settings = Settings()