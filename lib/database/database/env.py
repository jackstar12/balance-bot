from pydantic import SecretStr

from core.env import EnvBase


class Environment(EnvBase):
    DATABASE_URI: str
    DATABASE_TESTING_URI: str
    REDIS_URI: str

    encryption: SecretStr


environment = Environment()
