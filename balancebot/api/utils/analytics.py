import asyncio
from sqlalchemy import select

import msgpack
from datetime import datetime
from typing import Optional, Dict, List

import pytz

import balancebot.common.utils as utils
from balancebot.common.database import redis
from balancebot.common.database_async import db_first
from balancebot.common.dbmodels.balance import Balance
from balancebot.common.dbmodels.client import Client, add_client_filters
from balancebot.common.dbmodels.user import User
from balancebot.api.models.websocket import WebsocketConfig


async def create_cilent_analytics_serialized(client: Client, config: WebsocketConfig):

    cached = await get_cached_data(config)

    if cached:
        s = cached
        s['source'] = 'cache'
    else:
        s = await client.serialize(full=False, data=False)
        s['trades'] = {}
        s['source'] = 'database'

    cached_date = datetime.fromtimestamp(s.get('ts', 0), tz=pytz.UTC)

    now = datetime.now(tz=pytz.UTC)

    if config.since:
        since_date = max(config.since, cached_date)
    else:
        since_date = cached_date

    to_date = config.to or now
    since_date = since_date.replace(tzinfo=pytz.UTC)
    to_date = to_date.replace(tzinfo=pytz.UTC)

    if to_date > cached_date:
        since_date = max(since_date, cached_date)

        await update_client_data_balance(s, client, config, save_cache=False)

        trades = [await trade.serialize(data=True) for trade in client.trades if since_date <= trade.initial.time <= to_date]
        update_client_data_trades(s, trades, config, save_cache=False)

        s['ts'] = now.timestamp()
        asyncio.create_task(set_cached_data(s, config))

    return s
