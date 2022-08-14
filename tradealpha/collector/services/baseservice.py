import abc
import asyncio
import logging

import aiohttp
from aioredis import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from tradealpha.common.messenger import Messenger
from tradealpha.common.models.singleton import Singleton
from tradealpha.common.dbasync import async_maker


class BaseService:

    def __init__(self,
                 http_session: aiohttp.ClientSession,
                 messenger: Messenger,
                 redis: Redis,
                 scheduler: AsyncIOScheduler,
                 session_maker: sessionmaker,
                 **kwargs):
        self._http_session = http_session
        self._messenger = messenger
        self._redis = redis
        self._scheduler = scheduler
        self._db: AsyncSession = None
        self._db_maker = session_maker
        self._db_lock = asyncio.Lock()
        self._logger = logging.getLogger(f'Collector: {self.__class__.__name__}')

    async def init(self):
        pass

    async def run_forever(self):
        pass

    async def teardown(self):
        pass

    async def __aenter__(self):
        self._logger.info('Initialising')
        self._db = self._db_maker()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._logger.info('Exiting')
        await self._db.close()
        await self.teardown()
