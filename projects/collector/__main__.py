import asyncio

import aiohttp
from apscheduler.executors.asyncio import AsyncIOExecutor

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from collector.services.actionservice import ActionService
from collector.services.eventservice import EventService
from database.dbasync import redis, async_maker
from collector.services.cointracker import CoinTracker
from collector.services.alertservice import AlertService
from collector.services.dataservice import DataService
from collector.services.balanceservice import ExtendedBalanceService, BasicBalanceService
from common.messenger import Messenger, BALANCE, CLIENT, EVENT, TRADE
from core.utils import setup_logger
from collector.services.baseservice import BaseService


async def run_service(service: BaseService):
    async with service:
        await service.init()
        await service.run_forever()


async def run(session: aiohttp.ClientSession):
    setup_logger(debug=True)

    scheduler = AsyncIOScheduler(
        executors={
            'default': AsyncIOExecutor()
        }
    )

    service_args = (session, redis, scheduler, async_maker)

    data_service = DataService(*service_args)
    alert_service = AlertService(*service_args, data_service=data_service)
    coin_tracker = CoinTracker(*service_args, data_service=data_service)
    pnl_service = ExtendedBalanceService(*service_args,
                                         data_service=data_service)
    balance_service = BasicBalanceService(*service_args,
                                          data_service=data_service)
    action_service = ActionService(*service_args)
    event_service = EventService(*service_args)
    services = (data_service, alert_service, pnl_service, event_service, action_service, balance_service)

    scheduler.start()
    await asyncio.gather(
        *[run_service(service) for service in services]
    )


async def main():
    async with aiohttp.ClientSession() as session:
        await run(session)


if __name__ == '__main__':
    asyncio.run(main())
