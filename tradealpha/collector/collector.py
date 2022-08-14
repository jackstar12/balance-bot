import asyncio

import aiohttp
from apscheduler.executors.asyncio import AsyncIOExecutor

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from tradealpha.common.dbasync import redis, async_maker
from tradealpha.common.config import DATA_PATH, REKT_THRESHOLD
from tradealpha.common.exchanges import EXCHANGES
from tradealpha.collector.services.cointracker import CoinTracker
from tradealpha.collector.services.alertservice import AlertService
from tradealpha.collector.services.dataservice import DataService
from tradealpha.collector.services.balanceservice import ExtendedBalanceService, BasicBalanceService
from tradealpha.common.messenger import Messenger
from tradealpha.common.utils import setup_logger
from tradealpha.collector.services.baseservice import BaseService


async def run_service(service: BaseService):
    async with service:
        await service.init()
        await service.run_forever()


async def run(session: aiohttp.ClientSession):
    setup_logger()

    messenger = Messenger(redis)
    scheduler = AsyncIOScheduler(
        executors={
            'default': AsyncIOExecutor()
        }
    )

    service_args = (session, messenger, redis, scheduler, async_maker)

    data_service = DataService(*service_args)
    alert_service = AlertService(*service_args, data_service=data_service)
    coin_tracker = CoinTracker(*service_args, data_service=data_service)
    pnl_service = ExtendedBalanceService(*service_args,
                                         data_service=data_service)
    balance_service = BasicBalanceService(*service_args,
                                          data_service=data_service)

    services = (data_service, alert_service, pnl_service)

    scheduler.start()
    await asyncio.gather(
        *[run_service(service) for service in services]
    )


async def main():
    async with aiohttp.ClientSession() as session:
        await run(session)


if __name__ == '__main__':
    asyncio.run(main())
