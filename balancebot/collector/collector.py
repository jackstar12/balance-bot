import asyncio

import aiohttp

from balancebot.bot.config import EXCHANGES, FETCHING_INTERVAL_HOURS, DATA_PATH, REKT_THRESHOLD
from balancebot.collector.services.cointracker import CoinTracker
from balancebot.collector.services.alertservice import AlertService
from balancebot.collector.services.dataservice import DataService
from balancebot.collector.services.pnltracker import PnlService
from balancebot.collector.usermanager import UserManager
from balancebot.common.messenger import Messenger


async def run(session: aiohttp.ClientSession):

    user_manager = UserManager(exchanges=EXCHANGES,
                               fetching_interval_hours=FETCHING_INTERVAL_HOURS,
                               data_path=DATA_PATH,
                               rekt_threshold=REKT_THRESHOLD)

    messanger = Messenger()

    data_service = DataService(session)
    alert_service = AlertService(session)
    coin_tracker = CoinTracker(session)
    pnl_service = PnlService(session)

    await alert_service.initialize_alerts()
    await pnl_service.initialize_positions()
    await asyncio.gather(
        user_manager.start_fetching(),
        pnl_service.run_forever(),
        coin_tracker.run()
    )







if __name__ == '__main__':
    pass
