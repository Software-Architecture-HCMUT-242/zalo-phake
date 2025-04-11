from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    path_prefix: str = ''
    fastapi_secret_key: str = '1234567890'

settings = Settings()

def get_prefix(api_version: str) -> str:
    path_prefix = settings.path_prefix
    if not path_prefix.startswith('/'):
        path_prefix = f'/{path_prefix}'
    if path_prefix.endswith('/'):
        path_prefix = path_prefix.rstrip('/')
    return f'{path_prefix}{api_version}'