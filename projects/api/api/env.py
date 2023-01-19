from pydantic import SecretStr, HttpUrl

from core.env import EnvBase


class Env(EnvBase):
    OAUTH2_CLIENT_ID: str
    OAUTH2_CLIENT_SECRET: SecretStr
    OAUTH2_REDIRECT_URI: HttpUrl


ENV = Env()
