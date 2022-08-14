import os
from asyncio import Future
from dataclasses import dataclass

import pytest
from aioredis import Redis

from tradealpha.common import utils
from tradealpha.api.app import app
from tradealpha.common.dbsync import Base
from tradealpha.common.dbasync import REDIS_URI
from tradealpha.common.messenger import Messenger

import asyncio

import aioredis

from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from tradealpha.common import customjson

pytestmark = pytest.mark.anyio


SA_DATABASE_TESTING_URI = os.environ.get('DATABASE_TESTING_URI')
assert SA_DATABASE_TESTING_URI


@pytest.fixture(scope='session')
def engine():
    return create_async_engine(
        f'postgresql+asyncpg://{SA_DATABASE_TESTING_URI}',
        json_serializer=customjson.dumps_no_bytes,
        json_deserializer=customjson.loads,
    )


@pytest.fixture(scope='session')
async def tables(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope='session')
def session_maker(tables, engine):
    return sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope='function')
async def db(engine, session_maker) -> AsyncSession:
    async with session_maker() as db:
        yield db


@pytest.fixture(scope='session')
def redis() -> Redis:
    return aioredis.from_url(REDIS_URI)


@pytest.fixture(scope='session')
def messenger(redis) -> Messenger:
    return Messenger(redis=redis)


@dataclass
class Channel:
    name: str
    pattern: bool

    @classmethod
    def create(cls, *names, pattern=False):
        return cls(utils.join_args(*names), pattern)


@dataclass
class RedisTest:
    inputs: list[Channel]
    outputs: list[Channel]


@dataclass
class RedisMessages:
    channels: list[Channel]
    results: dict[str, Future]
    messenger: Messenger

    async def wait(self, timeout: float = 1):
        waiter = asyncio.gather(*self.results.values())
        try:
            await asyncio.wait_for(waiter, timeout)
        except asyncio.exceptions.TimeoutError:
            pytest.fail(f'Missed following messages:')
            #pytest.fail(f'Missed following messages:' + '\n\t'.join(name for name, fut in self.results.values() if not fut.done()))

    @classmethod
    def create(cls, *channels: Channel, messenger: Messenger):
        loop = asyncio.get_running_loop()
        return cls(
            channels=channels,
            results={
                c.name: loop.create_future()
                for c in channels
            },
            messenger=messenger
        )

    async def __aenter__(self):
        for channel in self.channels:
            await self.messenger.sub(
                pattern=True,
                **{channel.name: self.results[channel.name].set_result}
            )
        return self

    async def __aexit__(self, *args):
        for channel in self.channels:
            await self.messenger.unsub(channel.name, channel.pattern)


@pytest.fixture(scope='function')
async def redis_messages(request, messenger):
    async with RedisMessages.create(*request.param, messenger=messenger) as messages:
        yield messages


@pytest.fixture(scope='session')
def anyio_backend():
    return 'asyncio'
