from __future__ import annotations

import itertools
import typing
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Generator
from typing import TYPE_CHECKING

import pytz
from sqlalchemy import asc, select, func, desc, Date
from sqlalchemy.ext.asyncio import AsyncSession

import core as utils
from database.dbasync import db_all
from database.dbmodels.balance import Balance
from database.dbmodels.transfer import Transfer
from database.errors import UserInputError
from database.models.gain import Gain
from database.models.interval import Interval

if TYPE_CHECKING:
    from database.dbmodels.client import Client
    from database.dbmodels import Event


def create_daily(history: list[Balance],
                 transfers: list[Transfer],
                 ccy: str) -> list[Interval]:
    results = []

    # TODO: Optimize transfers
    offset_gen = transfer_gen(transfers, default_ccy=ccy, reset=True)

    # Initialise generator
    offset_gen.send(None)

    for prev, current in itertools.pairwise(history):
        try:
            offsets = offset_gen.send(current.time)
        except StopIteration:
            offsets = {}
        results.append(
            Interval.create(
                prev.get_currency(ccy),
                current.get_currency(ccy),
                offsets.get(ccy, 0)
            )
        )

    return results


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

    history: list[Balance] = await db_all(
        client.daily_balance_stmt(amount=amount, since=since, to=to),
        session=db
    )

    if len(history) == 0:
        if throw_exceptions:
            raise UserInputError(reason='Got no data for this user')
        else:
            return []

    return create_daily(history,
                        [t for t in client.transfers if history[0].time < t.time < history[-1].time],
                        client.currency)


_KT = typing.TypeVar('_KT')
_VT = typing.TypeVar('_VT')


def _add_safe(d: dict[_KT, _VT], key: _KT, val: _VT):
    d[key] = d.get(key, 0) + val


TOffset = dict[str, Decimal]


def transfer_gen(transfers: list[Transfer],
                 default_ccy: str,
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
        _add_safe(offsets, default_ccy, transfer.size)
        if transfer.extra_currencies:
            for ccy, amount in transfer.extra_currencies.items():
                _add_safe(offsets, ccy, Decimal(amount))

    # One last yield in case the next_time was beyond the last transfer
    yield offsets


async def calc_gains(clients: List[Client],
                     event: Event,
                     search: datetime,
                     currency: str = None) -> dict[Client, Gain]:
    """
    :param event:
    :param clients: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :return:
    """
    return {
        client: await client.calc_gain(event, search, currency=currency)
        for client in clients
    }
