import asyncio
import builtins
import itertools
import logging
from decimal import Decimal

from sqlalchemy import select

import msgpack
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import pytz

import balancebot.common.utils as utils
from balancebot.api.models.analytics import ClientAnalytics, FilteredPerformance, Performance, Calculation, \
    TradeAnalytics
from balancebot.common.database import redis
from balancebot.common.database_async import db_first
from balancebot.common.dbmodels.balance import Balance
from balancebot.common.dbmodels.client import Client, add_client_filters
from balancebot.common.dbmodels.user import User
from balancebot.api.models.websocket import ClientConfig
from balancebot.common.enums import Filter


logger = logging.getLogger(__name__)


async def get_cached_data(config):
    return


async def get_chached_filters(config: ClientConfig, filters: Tuple[Filter, ...], filter_calculation: Calculation):
    return
    await redis.hset()
    await redis.hget()


async def create_cilent_analytics(client: Client,
                                  config: ClientConfig,
                                  filters: Tuple[Filter, ...],
                                  filter_calculation: Calculation):

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

    # label_performance = {}
    # for label in user.labels:
    #     for trade in label.trades:
    #         if not trade.open_qty:
    #             label_performance[label.id] += trade.realized_pnl

#     daily = await utils.calc_daily(client)
#
#     weekday_performance = [0] * 7
#     for day in daily:
#         weekday_performance[day.day.weekday()] += day.diff_absolute

    performance_by_filter = {}
    trade_analytics = []
    #for trade in client.trades:
    #    all_filter_values = []
    #    for cur_filter in filters:
    #        if cur_filter == Filter.WEEKDAY:
    #            all_filter_values.append(
    #                ((cur_filter, trade.initial.time.weekday()),)
    #            )
    #        elif cur_filter == Filter.LABEL:
    #            # TODO: What if trade has no labels?
    #            all_filter_values.append(
    #                ((cur_filter, label.id) for label in trade.labels)
    #            )
    #        elif cur_filter == Filter.SESSION:
    #            filter_values = None  # TODO
    #        else:
    #            logger.warning(f'Invalid filter provided: {cur_filter}')
    #            continue
#
    #    for filter_value in itertools.product(*all_filter_values):
    #        if filter_value not in performance_by_filter:
    #            performance_by_filter[filter_value] = Performance(
    #                Decimal(0),
    #                Decimal(0),
    #                filter_values
    #            )
    #        if filter_calculation == Calculation.PNL:
    #            performance_by_filter[filter_value].absolute += trade.realized_pnl
    #    trade_analytics.append(
    #        TradeAnalytics.from_orm(trade)
    #    )

    return ClientAnalytics(
        id=client.id,
        filtered_performance=FilteredPerformance(
            filters=filters,
            performances=[]
            #performances=list(performance_by_filter.values())
        ),
        trades=trade_analytics
    )
