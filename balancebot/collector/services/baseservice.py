import abc
import logging

import aiohttp
from aioredis import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from balancebot.common.messenger import Messenger
from balancebot.common.models.singleton import Singleton
from common.dbasync import async_maker


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
        self._db: AsyncSession = None
        self._logger = logging.getLogger(self.__class__.__name__)

    async def init(self):
        pass

    async def run_forever(self):
        pass

    async def __aenter__(self):
        self._logger.info('Initialising')
        self._db = async_maker()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._logger.info('Exiting')
        await self._db.close()
