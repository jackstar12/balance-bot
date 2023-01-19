from pydantic import SecretStr, AnyHttpUrl

from core.env import EnvBase


class Env(EnvBase):
    OAUTH2_CLIENT_ID: str
    OAUTH2_CLIENT_SECRET: SecretStr
    OAUTH2_REDIRECT_URI: AnyHttpUrl


ENV = Env()
