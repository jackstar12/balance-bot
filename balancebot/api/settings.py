from datetime import timedelta
import os
from pydantic import BaseSettings
import dotenv


dotenv.load_dotenv('balancebot/api/.env')


class Settings(BaseSettings):
    authjwt_secret_key: str = os.environ.get('JWT_SECRET')
    authjwt_token_location: set = {"cookies"}
    authjwt_cookie_secure: bool = False
    authjwt_cookie_csrf_protect: bool = True
    authjwt_access_token_expires: timedelta = timedelta(minutes=30)
    authjwt_refresh_token_expires: timedelta = timedelta(hours=48)
    authjwt_cookie_max_age: int = timedelta(hours=48).total_seconds()
    authjwt_denylist_enabled: bool = True

    session_cookie_name: str = 'session-id'
    session_csfr_token_name: str = 'csrf'

    # authjwt_cookie_samesite: str = 'lax'

    class Config:
        env_file = ".env"


settings = Settings()
