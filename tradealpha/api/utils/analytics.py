import asyncio
import builtins
import itertools
import logging
import time
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select

import msgpack
from datetime import datetime
from typing import Optional, Dict, List, Tuple

import pytz

import tradealpha.common.utils as utils
from api.models.trade import DetailledTrade
from tradealpha.api.models.analytics import ClientAnalytics, FilteredPerformance, Performance, Calculation
from tradealpha.api.models.execution import Execution
from tradealpha.common.dbsync import redis
from tradealpha.common.dbasync import db_first
from tradealpha.common.dbmodels.balance import Balance
from tradealpha.common.dbmodels.client import Client, add_client_filters
from tradealpha.common.dbmodels.user import User
from tradealpha.api.models.websocket import ClientConfig
from tradealpha.common.enums import Filter


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
    for trade in client.trades:
        all_filter_values = []
        for cur_filter in filters:
            if cur_filter == Filter.WEEKDAY:
                all_filter_values.append(
                    ((cur_filter, trade.initial.time.weekday()),)
                )
            elif cur_filter == Filter.LABEL:
                # TODO: What if trade has no labels?
                all_filter_values.append(
                    ((cur_filter, label.id) for label in trade.labels)
                )
            elif cur_filter == Filter.SESSION:
                filter_values = None  # TODO
            else:
                logger.warning(f'Invalid filter provided: {cur_filter}')
                continue

        for filter_value in itertools.product(*all_filter_values):
            if filter_value not in performance_by_filter:
                performance_by_filter[filter_value] = Performance(
                    Decimal(0),
                    Decimal(0),
                    filter_value
                )
            if filter_calculation == Calculation.PNL:
                performance_by_filter[filter_value].absolute += trade.realized_pnl
        try:
            trade_analytics.append(
                DetailledTrade.from_orm(trade)
            )
        except ValidationError as e:
            logging.exception('Validation Error')

    return ClientAnalytics.construct(
        id=client.id,
        filtered_performance=FilteredPerformance.construct(
            filters=filters,
            performances=[]
            #performances=list(performance_by_filter.values())
        ),
        trades=trade_analytics
    )
