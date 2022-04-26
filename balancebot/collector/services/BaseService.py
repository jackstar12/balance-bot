import aiohttp
from aioredis import Redis

from balancebot.common.messenger import Messenger
from balancebot.common.models.singleton import Singleton


class BaseService(Singleton):

    def init(self, http_session: aiohttp.ClientSession, messenger: Messenger, redis: Redis, *args, **kwargs):
        self._http_session = http_session
        self._messenger = messenger
        self._redis = redis
