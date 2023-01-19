from typing import Optional

import dotenv
import os

from pydantic import BaseSettings, SecretStr


dotenv.load_dotenv()


class EnvBase(BaseSettings):
    class Config:
        env_file = ".env"


class Environment(EnvBase):
    TESTING: bool
    LOG_OUTPUT_DIR: str = "/LOGS/"
    DATA_PATH: str = "/data/"


env = Environment()

TESTING = env.TESTING
LOG_OUTPUT_DIR = env.LOG_OUTPUT_DIR
DATA_PATH = env.DATA_PATH
