import aiohttp
from aioredis import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from balancebot.common.messenger import Messenger
from balancebot.common.models.singleton import Singleton


class BaseService:

    def __init__(self,
                 http_session: aiohttp.ClientSession,
                 messenger: Messenger,
                 redis: Redis,
                 scheduler: AsyncIOScheduler,
                 *args, **kwargs):
        self._http_session = http_session
        self._messenger = messenger
        self._redis = redis
        self._scheduler = scheduler
