from pydantic import SecretStr

from core.env import EnvBase


class Env(EnvBase):
    BOT_KEY: SecretStr

environment = Env()
