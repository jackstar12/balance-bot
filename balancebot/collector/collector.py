import asyncio

import aiohttp

from balancebot.api.database import redis
from balancebot.bot.config import EXCHANGES, FETCHING_INTERVAL_HOURS, DATA_PATH, REKT_THRESHOLD
from balancebot.collector.services.cointracker import CoinTracker
from balancebot.collector.services.alertservice import AlertService
from balancebot.collector.services.dataservice import DataService
from balancebot.collector.services.balanceservice import BalanceService
from balancebot.collector.usermanager import UserManager
from balancebot.common.messenger import Messenger


async def run(session: aiohttp.ClientSession):

    user_manager = UserManager(exchanges=EXCHANGES,
                               fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                               data_path=DATA_PATH,
                               rekt_threshold=REKT_THRESHOLD)
    data_service = DataService(
        session, Messenger(), redis
    )
    alert_service = AlertService(session, Messenger(), redis, data_service=data_service)
    coin_tracker = CoinTracker(session, Messenger(), redis, data_service=data_service)
    pnl_service = BalanceService(session, Messenger(), redis,
                                 data_service=data_service,
                                 exchanges=EXCHANGES,
                                 fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                                 data_path=DATA_PATH,
                                 rekt_threshold=REKT_THRESHOLD)

    await alert_service.initialize_alerts()
    await asyncio.gather(
        pnl_service.run_forever(),
        coin_tracker.run()
    )

if __name__ == '__main__':
    pass
