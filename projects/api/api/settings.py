from datetime import timedelta
import os
from pydantic import BaseSettings, SecretStr


class Settings(BaseSettings):
    JWT_SECRET: str

    session_cookie_max_age: int = timedelta(hours=48).total_seconds()
    session_cookie_name: str = 'session'
    session_csfr_token_name: str = 'csrf'

    # authjwt_cookie_samesite: str = 'lax'

    class Config:
        env_file = ".env"


settings = Settings()
