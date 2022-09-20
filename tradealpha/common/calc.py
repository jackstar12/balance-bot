from __future__ import annotations
import itertools
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
                     string=False,
                     throw_exceptions=False,
                     since: datetime = None,
                     to: datetime = None,
                     currency: str = None,
                     db: AsyncSession = None) -> Union[List[Interval], str]:
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

    currency = currency or '$'
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

    subq = select(
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
        subq
    ).filter(
        subq.c.row_number == 1,
        Balance.id == subq.c.id
    ).order_by(
        asc(Balance.time)
    )

    history: list[Balance] = await db_all(stmt, Balance.client, session=db)

    if len(history) == 0:
        if throw_exceptions:
            raise UserInputError(reason='Got no data for this user')
        else:
            return "" if string else []

    if string:
        results = PrettyTable(
            field_names=["Date", "Amount", "Diff", "Diff %"]
        )
    else:
        results = []

    offset_gen = transfer_gen(client,
                              [t for t in client.transfers if since < t.time < to],
                              reset=True)
    offset_gen.send(None)

    for prev, current in itertools.pairwise(history):
        try:
            offsets = offset_gen.send(current.time)
        except StopIteration:
            offsets = {}
        values = Interval.create(
            prev.get_currency(client.currency),
            current.get_currency(client.currency),
            offsets.get(client.currency, 0)
        )
        if string:
            results.add_row([*values])
        else:
            results.append(values)

    return results


def _add_safe(dict, key, val):
    dict[key] = dict.get(key, 0) + val


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
