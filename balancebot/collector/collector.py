import asyncio
import logging

import aiohttp
from apscheduler.executors.asyncio import AsyncIOExecutor

import balancebot.common.dbmodels
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from balancebot.common.dbasync import redis
from balancebot.common.config import DATA_PATH, REKT_THRESHOLD
from balancebot.common.exchanges import EXCHANGES
from balancebot.collector.services.cointracker import CoinTracker
from balancebot.collector.services.alertservice import AlertService
from balancebot.collector.services.dataservice import DataService
from balancebot.collector.services.balanceservice import ExtendedBalanceService, BasicBalanceService
from balancebot.common.messenger import Messenger
from balancebot.common.utils import setup_logger
from balancebot.collector.services.baseservice import BaseService



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

    data_service = DataService(session, messenger, redis, scheduler, )
    alert_service = AlertService(session, messenger, redis, scheduler, data_service=data_service)
    coin_tracker = CoinTracker(session, messenger, redis, scheduler, data_service=data_service)
    pnl_service = ExtendedBalanceService(session, messenger, redis, scheduler,
                                         data_service=data_service,
                                         exchanges=EXCHANGES,
                                         data_path=DATA_PATH,
                                         rekt_threshold=REKT_THRESHOLD)
    balance_service = BasicBalanceService(session, messenger, redis, scheduler,
                                          data_service=data_service,
                                          exchanges=EXCHANGES,
                                          data_path=DATA_PATH,
                                          rekt_threshold=REKT_THRESHOLD)

    services = (data_service, alert_service, pnl_service, balance_service)

    scheduler.start()
    await asyncio.gather(
        *[run_service(service) for service in services]
    )


async def main():
    async with aiohttp.ClientSession() as session:
        await run(session)


if __name__ == '__main__':
    asyncio.run(main())
