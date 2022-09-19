import asyncio

import aiohttp
import pytest
import requests
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete

import tradealpha.collector.collector as collector
from tradealpha.collector.services.balanceservice import ExtendedBalanceService, BasicBalanceService
from tradealpha.collector.services.baseservice import BaseService
from tradealpha.collector.services.dataservice import DataService
from tradealpha.common import utils
from tradealpha.common.dbmodels.client import Client
from tradealpha.common.messenger import NameSpace, Category
from tests.conftest import RedisMessages, Channel
from tradealpha.common.dbmodels.user import User
from tradealpha.common.dbutils import register_client, delete_client
from tradealpha.common.exchanges import CCXT_CLIENTS

pytestmark = pytest.mark.anyio


@pytest.fixture(scope='session')
def session():
    with requests.Session() as session:
        yield session


async def run_service(service: BaseService):
    async with service:
        await service.init()
        task = asyncio.create_task(service.run_forever())
        yield service
        task.cancel()


@pytest.fixture(scope='session')
async def service_args(messenger, redis, session_maker):
    scheduler = AsyncIOScheduler(
        executors={'default': AsyncIOExecutor()}
    )
    async with aiohttp.ClientSession() as session:
        scheduler.start()
        return session, messenger, redis, scheduler, session_maker


@pytest.fixture(scope='session')
async def data_service(service_args):
    service = DataService(*service_args)
    yield await (run_service(service).__anext__())


@pytest.fixture(scope='session')
async def pnl_service(data_service, service_args):
    service = ExtendedBalanceService(*service_args, data_service=data_service)
    yield await (run_service(service).__anext__())


@pytest.fixture(scope='session')
async def balance_service(data_service, service_args):
    service = BasicBalanceService(*service_args, data_service=data_service)
    yield await (run_service(service).__anext__())


@pytest.fixture
async def test_user(db):

    await db.execute(
        delete(User)
    )
    await db.commit()

    user = User.mock()
    db.add(user)
    await db.commit()

    yield user

    await db.delete(user)
    await db.commit()


@pytest.fixture
async def db_client(request, time, db, test_user, messenger) -> Client:

    client: Client = request.param.create_client(test_user)
    client.last_execution_sync = client.last_transfer_sync = time

    await db.commit()

    async with RedisMessages.create(
        Channel.create(NameSpace.CLIENT, Category.ADDED),
        messenger=messenger
    ) as listener:
        await register_client(client, messenger, db)
        await listener.wait(30)

    try:
        yield client
    finally:
        async with RedisMessages.create(
            Channel.create(NameSpace.CLIENT, Category.REMOVED),
            messenger=messenger
        ) as listener:
            await delete_client(client, messenger, db)
            await listener.wait(.5)


@pytest.fixture
def ccxt_client(db_client, session):
    ccxt_class = CCXT_CLIENTS[db_client.exchange]
    ccxt = ccxt_class({
        'api_key': db_client.api_key,
        'secret': db_client.api_secret,
        'session': session,
        **(db_client.extra_kwargs or {})
    })

    ccxt.set_sandbox_mode(db_client.sandbox)

    return ccxt

