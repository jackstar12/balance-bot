import asyncio
from sqlalchemy import select

import msgpack
from datetime import datetime
from typing import Optional, Dict, List

import pytz

import balancebot.common.utils as utils
from balancebot.api.database import redis
from balancebot.api.database_async import db_first
from balancebot.api.dbmodels.balance import Balance
from balancebot.api.dbmodels.client import Client, add_client_filters
from balancebot.api.dbmodels.user import User
from balancebot.api.models.websocket import WebsocketConfig


def ratio(a: float, b: float):
    return round(a / (a + b), ndigits=3) if a + b > 0 else 0.5


def update_dicts(*dicts: Dict, **kwargs):
    for arg in dicts:
        arg.update(kwargs)


def update_client_data_trades(cache: Dict, trades: List[Dict], config: WebsocketConfig, save_cache=True):

    result = {}
    new_trades = {}
    existing_trades = cache['trades']
    now = datetime.now(tz=pytz.utc)

    winners, losers = cache.get('winners', 0), cache.get('losers', 0)
    total_win, total_loss = cache.get('avg_win', 0.0) * winners, cache.get('avg_loss', 0.0) * losers

    for trade in trades:
        # Get existing entry
        existing = existing_trades.get(trade['id'])
        if trade['status'] == 'win':
            winners += 1
            total_win += trade['realized_pnl']
        elif trade['status'] == 'loss':
            losers += 1
            total_loss += trade['realized_pnl']
        update_dicts(
            result, cache
        )
        new_trades[trade['id']] = existing_trades[trade['id']] = trade

    update_dicts(result, trades=new_trades)

    update_dicts(
        result, cache,
        winners=winners,
        losers=losers,
        avg_win=total_win / winners if winners else 1,
        avg_loss=total_loss / losers if losers else 1,
        win_ratio=ratio(winners, losers),
        ts=now.timestamp()
    )

    if save_cache:
        asyncio.create_task(set_cached_data(cache, config))

    return result


async def update_client_data_balance(cache: Dict, client: Client, config: WebsocketConfig, save_cache=True) -> Dict:

    cached_date = datetime.fromtimestamp(cache.get('ts', 0), tz=pytz.UTC)
    now = datetime.now(tz=pytz.UTC)

    if config.since:
        since_date = max(config.since, cached_date)
    else:
        since_date = cached_date

    result = {}

    new_history = []

    async def append(balance: Balance):
        new_history.append(await balance.serialize(full=True, data=True, currency=config.currency))

    daily = await utils.calc_daily(
        client=client,
        throw_exceptions=False,
        since=since_date,
        to=config.to,
        now=now,
        forEach=append
    )
    result['history'] = new_history
    cache['history'] += new_history

    winning_days, losing_days = cache.get('winning_days', 0), cache.get('losing_days', 0)
    for day in daily:
        if day.diff_absolute > 0:
            winning_days += 1
        elif day.diff_absolute < 0:
            losing_days += 1
    result['daily'] = daily

    # When updating daily cache it's important to set the last day to the current day
    daily_cache = cache.get('daily', [])
    if daily:
        if daily_cache and cached_date.weekday() == now.weekday():
            daily_cache[len(daily_cache) - 1] = daily[0]
            daily_cache += daily[1:]
        else:
            daily_cache += daily
    cache['daily'] = daily_cache

    update_dicts(
        result, cache,
        daily_win_ratio=ratio(winning_days, losing_days),
        winning_days=winning_days,
        losing_days=losing_days,
        ts=now.timestamp()
    )

    if save_cache:
        asyncio.create_task(set_cached_data(cache, config))

    return result


async def get_cached_data(config: WebsocketConfig):
    redis_key = f'client:data:{config.id}:{config.since.timestamp() if config.since else None}:{config.to.timestamp() if config.to else None}:{config.currency}'
    cached = await redis.get(redis_key)
    if cached:
        return msgpack.unpackb(cached, raw=False)


async def set_cached_data(data: Dict, config: WebsocketConfig):
    redis_key = f'client:data:{config.id}:{config.since.timestamp() if config.since else None}:{config.to.timestamp() if config.to else None}:{config.currency}'
    await redis.set(redis_key, msgpack.packb(data))


async def create_cilent_data_serialized(client: Client, config: WebsocketConfig):

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

        trades = [await trade.serialize(data=True) for trade in client.trades if since_date <= trade.initial.tz_time <= to_date]
        update_client_data_trades(s, trades, config, save_cache=False)

        s['ts'] = now.timestamp()
        asyncio.create_task(set_cached_data(s, config))

    return s


async def get_user_client(user: User, id: int = None):
    client: Optional[Client] = None
    if id:
        client = await db_first(add_client_filters(select(Client), user, id))
    elif user.discord_user:
        # TODO: Load client seperately?
        pass
    elif len(user.clients) > 0:
        client = user.clients[0]
    return client
