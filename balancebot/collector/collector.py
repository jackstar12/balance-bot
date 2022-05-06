import asyncio
import aiohttp
import balancebot.common.dbmodels
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from balancebot.common.database_async import redis
from balancebot.common.config import DATA_PATH, REKT_THRESHOLD
from balancebot.common.exchanges import EXCHANGES
from balancebot.collector.services.cointracker import CoinTracker
from balancebot.collector.services.alertservice import AlertService
from balancebot.collector.services.dataservice import DataService
from balancebot.collector.services.balanceservice import BalanceService
from balancebot.common.messenger import Messenger


async def run(session: aiohttp.ClientSession):

    scheduler = AsyncIOScheduler()

    data_service = DataService(session, Messenger(), redis,  scheduler,)
    alert_service = AlertService(session, Messenger(), redis, scheduler, data_service=data_service)
    coin_tracker = CoinTracker(session, Messenger(), redis, scheduler, data_service=data_service)
    pnl_service = BalanceService(session, Messenger(), redis, scheduler,
                                 data_service=data_service,
                                 exchanges=EXCHANGES,
                                 data_path=DATA_PATH,
                                 rekt_threshold=REKT_THRESHOLD)

    await alert_service.initialize_alerts()
    await asyncio.gather(
        pnl_service.run_forever()
        # coin_tracker.run()
    )


async def main():
    async with aiohttp.ClientSession() as session:
        await run(session)


if __name__ == '__main__':
    asyncio.run(main())
