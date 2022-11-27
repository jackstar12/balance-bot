import asyncio
import logging
from functools import wraps

import aiohttp
from aioredis import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from common.messenger import Messenger
from core import call_unknown_function


class BaseService:

    def __init__(self,
                 http_session: aiohttp.ClientSession,
                 redis: Redis,
                 scheduler: AsyncIOScheduler,
                 session_maker: sessionmaker,
                 **kwargs):
        self._http_session = http_session
        self._messenger = Messenger(redis)
        self._redis = redis
        self._scheduler = scheduler
        self._db: AsyncSession = None
        self._db_maker = session_maker
        self._db_lock = asyncio.Lock()
        self._logger = logging.getLogger(f'Collector: {self.__class__.__name__}')

    async def init(self):
        pass

    def table_decorator(self, table):
        def decorator(coro):
            @wraps(coro)
            async def wrapper(data: dict):
                async with self._db_lock:
                    instance = await self._db.get(table, data['id'], populate_existing=True)
                return await call_unknown_function(coro, instance)

            return wrapper

        return decorator

    async def run_forever(self):
        # Do nothing, required because otherwise service would finish and the db session would close
        fut = asyncio.get_running_loop().create_future()
        await fut

    async def teardown(self):
        pass

    async def __aenter__(self):
        self._logger.info('Initialising')
        self._db = self._db_maker()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._logger.info('Exiting')
        await self._db.close()
        await self.teardown()
