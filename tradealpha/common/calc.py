from __future__ import annotations
import itertools
from datetime import datetime, timedelta, date
from typing import List, Callable, Union, Any
from typing import TYPE_CHECKING

import pytz
from prettytable import PrettyTable
from sqlalchemy import asc, select, func, desc, Date
from sqlalchemy.ext.asyncio import AsyncSession
import tradealpha.common.utils as utils

from tradealpha.common import dbutils
from tradealpha.common.models.gain import ClientGain
from tradealpha.common.dbasync import async_session, db_all, redis
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

    history = await db_all(stmt, session=db)

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

    for prev, current in itertools.pairwise(history):
        values = Interval.create(prev, current)
        if string:
            results.add_row([*values])
        else:
            results.append(values)

    return results


async def calc_intervals(client: Client,
                         interval: timedelta,
                         limit: int = None,
                         guild_id: int = None,
                         currency: str = None,
                         since: date = None,
                         to: date = None,
                         as_string=False,
                         forEach: Callable[[Balance], Any] = None,
                         throw_exceptions=True,
                         today: date = None,
                         db_session: AsyncSession = None) -> Union[List[Interval], str]:
    """
    Calculates daily balance changes for a given client.
    :param interval:
    :param today:
    :param limit:
    :param since:
    :param to:
    :param throw_exceptions:
    :param forEach: function to be performed for each balance
    :param client: Client to calculate changes
    :param amount: Amount of days to calculate
    :param guild_id:
    :param currency: Currency that will be used
    :param as_string: Whether the created table should be stored as a string using prettytable or as a list of
    :return:
    """
    db_session = db_session or async_session
    currency = currency or '$'
    today = today or date.today()
    since = since or date.fromtimestamp(0)
    to = to or today

    end = min(today, to)

    history = await db_all(
        client.history.statement.filter(
            Balance.time > since, Balance.time < today
        ).order_by(
            asc(Balance.time)
        ),
        session=db_session
    )

    if len(history) == 0:
        if throw_exceptions:
            raise UserInputError(reason='Got no data for this user')
        else:
            return "" if as_string else []

    if limit:
        try:
            start = end - interval * limit
        except OverflowError:
            raise UserInputError('Invalid daily amount given')
    else:
        start = history[0].time.date()

    start = max(since, start)

    if guild_id:
        event = await dbutils.get_discord_event(guild_id)
        if event and event.start > start:
            start = event.start

    current_search = start + interval
    prev = prev_balance = history[0]

    if as_string:
        results = PrettyTable(
            field_names=["Date", "Amount", "Diff", "Diff %"]
        )
    else:
        results = []
    for balance in history:
        now = balance.time.date()
        if current_search <= now <= to:
            # current = get_best_time_fit(current_search, prev_balance, balance)
            prev = prev or prev_balance
            values = Interval.create(prev, prev_balance, as_string)
            if as_string:
                results.add_row(list(values)[4:])
            else:
                results.append(values)
            prev = prev_balance
            current_search = now + interval
        prev_balance = balance
        await utils.call_unknown_function(forEach, balance)

    # if prev_balance.time.date() < current_search:
    #    values = _create_interval(prev, history[len(history) - 1], as_string)
    #    if as_string:
    #        results.add_row([*values])
    #    else:
    #        results.append(values)
    #
    return results


async def calc_gain(client: Client,
                    event: Event,
                    since: datetime,
                    db: AsyncSession,
                    currency: str = None):
    if currency is None:
        currency = 'USD'

    if event:
        since = max(since, event.start)

    balance_then = await client.get_exact_balance_at_time(since, db=db, currency=currency)
    balance_now = await client.get_latest_balance(redis=redis, db=db)

    if balance_then and balance_now:
        diff = round(balance_now.unrealized - balance_then.unrealized,
                     ndigits=utils.config.CURRENCY_PRECISION.get(currency, 3))
        absolute, relative = balance_then.get_currency(currency).gain_since(balance_now.get_currency())
        if balance_then.unrealized > 0:
            return ClientGain(
                client=client,
                relative=round(100 * (diff / balance_then.unrealized),
                               ndigits=utils.config.CURRENCY_PRECISION.get('%', 2)),
                absolute=diff
            )
        else:
            return ClientGain(client, utils.Decimal(0), diff)
    else:
        return ClientGain(client, None, None)


async def calc_gains(clients: List[Client],
                     event: Event,
                     search: datetime,
                     db: AsyncSession,
                     currency: str = None) -> List[ClientGain]:
    """
    :param event:
    :param clients: users to calculate gain for
    :param search: date since when gain should be calculated
    :param currency:
    :return:
    Gain for each user is stored in a list of tuples following this structure: (User, (user gain rel, user gain abs)) success
                                                                               (User, None) missing
    """
    return [
        await calc_gain(client, event, search, db=db, currency=currency)
        for client in clients
    ]
