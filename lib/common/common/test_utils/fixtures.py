import asyncio
import os
from asyncio import Future
from dataclasses import dataclass
from typing import Any, Callable

import aioredis
import pytest
from aioredis import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from common.test_utils.mockexchange import MockExchange, MockTicker
from core import json as customjson
from database.dbmodels import Event, Client, EventEntry, Balance
from database.dbmodels.trade import Trade
from database.dbsync import Base
from common.exchanges import EXCHANGES, EXCHANGE_TICKERS
from common.messenger import Messenger, NameSpaceInput
from database.env import environment

pytestmark = pytest.mark.anyio


SA_DATABASE_TESTING_URI = os.environ.get('DATABASE_TESTING_URI')
assert SA_DATABASE_TESTING_URI


EXCHANGES['mock'] = MockExchange
EXCHANGE_TICKERS['mock'] = MockTicker

@pytest.fixture(scope='session')
def engine():
    return create_async_engine(
        f'postgresql+asyncpg://{environment.DATABASE_TESTING_URI}',
        json_serializer=customjson.dumps_no_bytes,
        json_deserializer=customjson.loads,
    )


@pytest.fixture(scope='session')
async def tables(engine):
    async with engine.begin() as conn:
        #await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope='session')
def session_maker(tables, engine):
    return sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope='function')
async def db(tables, engine, session_maker) -> AsyncSession:
    async with session_maker() as db:
        yield db


@pytest.fixture(scope='session')
def redis() -> Redis:
    return aioredis.from_url(environment.REDIS_URI)


@pytest.fixture(scope='session')
def messenger(redis) -> Messenger:
    messenger = Messenger(redis=redis)
    return messenger


@dataclass
class Channel:
    ns: NameSpaceInput
    topic: Any
    validate: Callable[[dict], bool] = None


@dataclass
class Messages:
    channels: list[Channel]
    results: dict[str, Future]
    messenger: Messenger

    async def wait(self, timeout: float = 1):
        waiter = asyncio.gather(*self.results.values())
        waiter.cancelled()
        try:
            result = await asyncio.wait_for(waiter, timeout)
            return result
        except asyncio.exceptions.TimeoutError:
            pytest.fail(f'Missed following messages:' + '\n\t'.join(name for name, fut in self.results.values() if fut.cancelled()))

    @classmethod
    def create(cls, *channels: Channel, messenger: Messenger):
        loop = asyncio.get_running_loop()
        return cls(
            channels=list(channels),
            results={
                c.ns.name + str(c.topic): loop.create_future()
                for c in channels
            },
            messenger=messenger
        )

    async def __aenter__(self):

        async def register_channel(channel: Channel):
            def callback(data):
                if not channel.validate or channel.validate(data):
                    fut = self.results[channel.ns.name + str(channel.topic)]
                    if not fut.done():
                        fut.set_result(data)

            await self.messenger.sub_channel(
                channel.ns,
                channel.topic,
                callback
            )

        for channel in self.channels:
            await register_channel(channel)
        return self

    async def __aexit__(self, *args):
        for channel in self.channels:
            await self.messenger.unsub_channel(channel.ns, channel.topic)


@pytest.fixture(scope='function')
async def redis_messages(request, messenger):
    async with Messages.create(*request.param, messenger=messenger) as messages:
        yield messages


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'
