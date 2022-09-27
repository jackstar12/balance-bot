from __future__ import annotations
import itertools
import typing
from collections import OrderedDict
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import List, Callable, Union, Any, Generator
from typing import TYPE_CHECKING

import pytz
from prettytable import PrettyTable
from sqlalchemy import asc, select, func, desc, Date
from sqlalchemy.ext.asyncio import AsyncSession
import tradealpha.common.utils as utils

from tradealpha.common import dbutils
from tradealpha.common.dbmodels.transfer import Transfer
from tradealpha.common.models.gain import ClientGain, Gain
from tradealpha.common.dbasync import async_session, db_all, redis, db_select, db_select_all
from tradealpha.common.dbmodels.balance import Balance
from tradealpha.common.errors import UserInputError
from tradealpha.common.models.interval import Interval

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.client import Client
    from tradealpha.common.dbmodels import Event


async def calc_daily(client: Client,
                     amount: int = None,
                     throw_exceptions=False,
                     since: datetime = None,
                     to: datetime = None,
                     currency: str = None,
                     db: AsyncSession = None) -> List[Interval]:
    """
    Calculates daily balance changes for a given client.
    :param since:
    :param to:
    :param throw_exceptions:
    :param client: Client to calculate changes
    :param amount: Amount of days to calculate
    :param currency: Currency that will be used
    :param string: Whether the created table should be stored as a string using prettytable or as a list of
    :return:
    """
    now = utils.utc_now()

    currency = currency or 'USD'
    since = since or datetime.fromtimestamp(0, pytz.utc)
    to = to or now

    since_date = since.replace(tzinfo=pytz.UTC).replace(hour=0, minute=0, second=0)
    daily_end = min(now, to)

    if amount:
        try:
            daily_start = daily_end - timedelta(days=amount - 1)
        except OverflowError:
            raise UserInputError('Invalid daily amount given')
    else:
        daily_start = since_date

    # We always want to fetch the last balance of the date (first balance of next date),
    # so we need to partition by the current date and order by
    # time in descending order so that we can pick out the first (last) one

    sub = select(
        func.row_number().over(
            order_by=desc(Balance.time),
            partition_by=Balance.time.cast(Date)
        ).label('row_number'),
        Balance.id.label('id')
    ).filter(
        Balance.client_id == client.id,
        Balance.time > daily_start
    ).subquery()

    stmt = select(
        Balance,
        sub
    ).filter(
        sub.c.row_number == 1,
        Balance.id == sub.c.id
    ).order_by(
        asc(Balance.time)
    )

    history: list[Balance] = await db_all(stmt, Balance.client, session=db)

    if len(history) == 0:
        if throw_exceptions:
            raise UserInputError(reason='Got no data for this user')
        else:
            return []

    results = []

    # TODO: Optimize transfers
    offset_gen = transfer_gen(client,
                              [t for t in client.transfers if history[0].time < t.time < history[-1].time],
                              reset=True)

    # Initialise generator
    offset_gen.send(None)

    for prev, current in itertools.pairwise(history):
        try:
            offsets = offset_gen.send(current.time)
        except StopIteration:
            offsets = {}
        results.append(
            Interval.create(
                prev.get_currency(client.currency),
                current.get_currency(client.currency),
                offsets.get(client.currency, 0)
            )
        )

    return results


_KT = typing.TypeVar('_KT')
_VT = typing.TypeVar('_VT')


def _add_safe(d: dict[_KT, _VT], key: _KT, val: _VT):
    d[key] = d.get(key, 0) + val


TOffset = dict[str, Decimal]


def transfer_gen(client: Client,
                 transfers: list[Transfer],
                 reset=False) -> Generator[TOffset, datetime, None]:
    # transfers = await db_select_all(
    #     Transfer,
    #     Transfer.client_id == client.id,
    #     Transfer.time > since,
    #     Transfer.time < to,
    #     session=db
    # )
    offsets: TOffset = {}

    next_time: datetime = yield
    for transfer in transfers:
        while next_time < transfer.time:
            next_time = yield offsets
            if reset:
                offsets = {}
        _add_safe(offsets, client.currency, transfer.amount)
        if transfer.extra_currencies:
            for ccy, amount in transfer.extra_currencies.items():
                _add_safe(offsets, ccy, Decimal(amount))

    # One last yield in case the next_time was beyond the last transfer
    yield offsets


async def calc_gains(clients: List[Client],
                     event: Event,
                     search: datetime,
                     db: AsyncSession,
                     currency: str = None) -> dict[Client, Gain]:
    """
    :param event:
    :param clients: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :return:
    """
    return {
        client: await client.calc_gain(event, search, db=db, currency=currency)
        for client in clients
    }
