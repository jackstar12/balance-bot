from __future__ import annotations

import asyncio
import itertools
import os
import re
import logging
import sys
import traceback
import typing
from asyncio import Future
from decimal import Decimal
from enum import Enum
from functools import wraps

import discord
import inspect
import matplotlib.pyplot as plt
import pytz

from prettytable import PrettyTable

from discord_slash.utils.manage_components import create_button, create_actionrow, create_select_option
import discord_slash.utils.manage_components as discord_components
from discord_slash.model import ButtonStyle
from discord_slash import SlashCommand, ComponentContext, SlashContext
from datetime import datetime, timedelta, date
from typing import List, Tuple, Callable, Optional, Union, Dict, Any, Sequence, Iterable

from sqlalchemy import asc, select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

import tradealpha.common.dbmodels.event as db_event
import tradealpha.common.dbmodels.client as db_client
from tradealpha.common.dbasync import async_session, db_all
from tradealpha.common.dbmodels.guildassociation import GuildAssociation
from tradealpha.common.errors import UserInputError, InternalError
from tradealpha.common.models.daily import Daily, Interval
from tradealpha.common.models.gain import ClientGain
from tradealpha.common import dbutils
from tradealpha.common.dbmodels.balance import Balance
from tradealpha.common.models.selectionoption import SelectionOption
import tradealpha.common.config as config
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.client import Client


def now():
    return datetime.now(pytz.utc)


def date_string(d: date | datetime):
    return d.strftime('%Y-%m-%d')


# Some consts to make TF tables prettier
MINUTE = 60
HOUR = MINUTE * 60
DAY = HOUR * 24
WEEK = DAY * 7

_regrex_pattern = re.compile("["
                             u"\U0001F600-\U0001F64F"  # emoticons
                             u"\U0001F300-\U0001F5FF"  # symbols & pictographs
                             u"\U0001F680-\U0001F6FF"  # transport & map symbols
                             u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
                             u"\U00002500-\U00002BEF"  # chinese char
                             u"\U00002702-\U000027B0"
                             u"\U00002702-\U000027B0"
                             u"\U000024C2-\U0001F251"
                             u"\U0001f926-\U0001f937"
                             u"\U00010000-\U0010ffff"
                             u"\u2640-\u2642"
                             u"\u2600-\u2B55"
                             u"\u200d"
                             u"\u23cf"
                             u"\u23e9"
                             u"\u231a"
                             u"\ufe0f"  # dingbats
                             u"\u3030"
                             "]+", re.UNICODE)


# Thanks Stackoverflow
def de_emojify(text):
    return _regrex_pattern.sub(r'', text)


def get_best_time_fit(search: datetime, prev: Balance, after: Balance):
    if abs((prev.tz_time - search).total_seconds()) < abs((after.tz_time - search).total_seconds()):
        return prev
    else:
        return after


def embed_add_value_safe(embed: discord.Embed, name, value, **kwargs):
    if value:
        embed.add_field(name=name, value=value, **kwargs)


def setup_logger(debug: bool = False):
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if debug else logging.INFO)  # Change this to DEBUG if you want a lot more info
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    print(os.path.abspath(config.LOG_OUTPUT_DIR))
    if not os.path.exists(config.LOG_OUTPUT_DIR):
        os.mkdir(config.LOG_OUTPUT_DIR)
    if config.TESTING or True:
        log_stream = sys.stdout
    else:
        log_stream = open(config.LOG_OUTPUT_DIR + f'log_{datetime.now().strftime("%Y-%m-%d_%H_%M_%S")}.txt', "w")
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger





async def calc_daily(client: Client,
                     amount: int = None,
                     guild_id: int = None,
                     currency: str = None,
                     string=False,
                     forEach: Callable[[Balance], Any] = None,
                     throw_exceptions=True,
                     since: datetime = None,
                     to: datetime = None,
                     now: datetime = None) -> Union[List[Daily], str]:
    """
    Calculates daily balance changes for a given client.
    :param since:
    :param to:
    :param throw_exceptions:
    :param forEach: function to be performed for each balance
    :param client: Client to calculate changes
    :param amount: Amount of days to calculate
    :param guild_id:
    :param currency: Currency that will be used
    :param string: Whether the created table should be stored as a string using prettytable or as a list of
    :return:
    """

    if currency is None:
        currency = '$'

    if now is None:
        now = datetime.now(tz=pytz.UTC)

    if since is None:
        since = datetime.fromtimestamp(0)

    if to is None:
        to = now

    since_date = since.replace(tzinfo=pytz.UTC).replace(hour=0, minute=0, second=0)

    daily_end = min(now, to)

    history = await db_all(client.history.statement.filter(
        Balance.time > since_date, Balance.time < now
    ).order_by(
        asc(Balance.time)
    ))

    if len(history) == 0:
        if throw_exceptions:
            raise UserInputError(reason='Got no data for this user')
        else:
            return "" if string else []

    if amount:
        try:
            daily_start = daily_end - timedelta(days=amount - 1)
        except OverflowError:
            raise UserInputError('Invalid daily amount given')
    else:
        daily_start = history[0].time

    daily_start = daily_start.replace(tzinfo=pytz.UTC)
    daily_start = max(since_date, daily_start).replace(hour=0, minute=0, second=0)

    if guild_id:
        event = await dbutils.get_event(guild_id)
        if event and event.start > daily_start:
            daily_start = event.start

    current_day = daily_start
    current_search = daily_start + timedelta(days=1)
    prev_balance = db_match_balance_currency(history[0], currency)
    prev_daily = history[0]
    prev_daily.time = prev_daily.time.replace(hour=0, minute=0, second=0)

    if string:
        results = PrettyTable(
            field_names=["Date", "Amount", "Diff", "Diff %"]
        )
    else:
        results = []
    for balance in history:
        if since <= balance.time <= to:
            if balance.time >= current_search:

                daily = db_match_balance_currency(get_best_time_fit(current_search, prev_balance, balance), currency)
                daily.time = daily.time.replace(minute=0, second=0)
                prev_daily = prev_daily or daily
                values = Daily(
                    day=date_string(current_day) if string else current_day.timestamp(),
                    amount=daily.unrealized,
                    diff_absolute=round(daily.unrealized - prev_daily.unrealized, ndigits=config.CURRENCY_PRECISION.get(currency, 2)),
                    diff_relative=calc_percentage(prev_daily.unrealized, daily.unrealized, string=False)
                )
                if string:
                    results.add_row([*values])
                else:
                    results.append(values)
                prev_daily = daily
                current_day = current_search
                current_search = current_search + timedelta(days=1)
            prev_balance = balance
        if balance.time > since_date:
            await call_unknown_function(forEach, balance)

    if prev_balance.time < current_search:
        values = Daily(
            day=date_string(current_day) if string else current_day.timestamp(),
            amount=prev_balance.unrealized,
            diff_absolute=round(prev_balance.unrealized - prev_daily.unrealized,
                                ndigits=config.CURRENCY_PRECISION.get(currency, 2)),
            diff_relative=calc_percentage(prev_daily.unrealized, prev_balance.unrealized, string=False)
        )
        if string:
            results.add_row([*values])
        else:
            results.append(values)

    return results


def create_interval(prev: Balance, current: Balance, as_string: bool) -> Interval:
    return Interval(
        current.time.strftime('%Y-%m-%d') if as_string else current.time.date(),
        amount=current.total,
        # diff_absolute=round(current.unrealized - prev.unrealized, ndigits=CURRENCY_PRECISION.get(currency, 2)),
        diff_absolute=current.total_transfers_corrected - prev.total_transfers_corrected,
        diff_relative=calc_percentage(
            prev.total, current.total - (current.total_transfered - prev.total_transfered), string=False),
        start_balance=prev,
        end_balance=current
    )


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
        event = await dbutils.get_event(guild_id)
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
            values = create_interval(prev, prev_balance, as_string)
            if as_string:
                results.add_row(list(values)[4:])
            else:
                results.append(values)
            prev = prev_balance
            current_search = now + interval
        prev_balance = balance
        await call_unknown_function(forEach, balance)

    # if prev_balance.time.date() < current_search:
    #    values = _create_interval(prev, history[len(history) - 1], as_string)
    #    if as_string:
    #        results.add_row([*values])
    #    else:
    #        results.append(values)
    #
    return results


def calc_percentage(then: Union[float, Decimal], now: Union[float, Decimal], string=True) -> float | str | Decimal:
    diff = now - then
    num_cls = type(then)
    if diff == 0.0:
        result = '0'
    elif then > 0:
        result = f'{round(100 * (diff / then), ndigits=3)}'
    else:
        result = '0'
    return result if string else num_cls(result)


async def create_leaderboard(dc_client: discord.Client,
                             guild_id: int,
                             mode: str,
                             event: db_event.Event = None,
                             time: datetime = None,
                             archived=False) -> discord.Embed:

    client_scores: List[Tuple[Client, float]] = []
    value_strings: Dict[Client, str] = {}
    clients_rekt: List[Client] = []
    clients_missing: List[Client] = []

    footer = ''
    description = ''

    guild = dc_client.get_guild(guild_id)
    if not guild:
        raise InternalError(f'Provided guild_id is not valid!')

    if not event:
        event = await dbutils.get_event(guild_id, throw_exceptions=False, eager_loads=[db_event.Event.registrations])

    if event:
        clients = event.registrations
    else:
        # All global clients
        clients = await db_all(
            select(db_client.Client).
                filter(
                db_client.Client.id.in_(
                    select(GuildAssociation.client_id).
                        filter_by(guild_id=guild.id)
                )
            )
        )

    # if not archived:
    #     user_manager = UserManager()
    #     await user_manager.fetch_data(clients=clients)

    if mode == 'balance':
        for client in clients:
            if client.rekt_on:
                clients_rekt.append(client)
                continue
            balance = await client.latest()
            if balance and not (event and balance.time < event.start):
                if balance.unrealized > config.REKT_THRESHOLD:
                    client_scores.append((client, balance.unrealized))
                    value_strings[client] = balance.to_string(display_extras=False)
                else:
                    clients_rekt.append(client)
            else:
                clients_missing.append(client)

    elif mode == 'gain':

        description += f'Gain {readable_time(time)}\n\n'

        client_gains = await calc_gains(clients, event, time)

        for gain in client_gains:
            if gain.relative is not None:
                if gain.client.rekt_on:
                    clients_rekt.append(gain.client)
                else:
                    client_scores.append((gain.client, gain.relative))
                    value_strings[gain.client] = f'{gain.relative}% ({gain.absolute}$)'
            else:
                clients_missing.append(gain.client)
    else:
        raise InternalError(f'Unknown mode {mode} was passed in')

    client_scores.sort(key=lambda x: x[1], reverse=True)
    rank = 1
    rank_true = 1

    if len(client_scores) > 0:
        if mode == 'gain' and not archived:
            dc_client.loop.create_task(
                dc_client.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=f'Best Trader: {client_scores[0][0].discord_user.get_display_name(dc_client, guild_id)}'
                    )
                )
            )

        prev_score = None
        for client, score in client_scores:
            member = guild.get_member(client.discord_user.id)
            if member:
                if prev_score is not None and score < prev_score:
                    rank = rank_true
                if client in value_strings:
                    value = value_strings[client]
                    description += f'{rank}. **{member.display_name}** {value}\n'
                    rank_true += 1
                else:
                    logging.error(f'Missing value string for {client=} even though hes in user_scores')
                prev_score = score

    if len(clients_rekt) > 0:
        description += f'\n**Rekt**\n'
        for user_rekt in clients_rekt:
            member = guild.get_member(user_rekt.discord_user.id)
            if member:
                description += f'{member.display_name}'
                if user_rekt.rekt_on:
                    description += f' since {user_rekt.rekt_on.replace(microsecond=0)}'
                description += '\n'

    if len(clients_missing) > 0:
        description += f'\n**Missing**\n'
        for client_missing in clients_missing:
            member = guild.get_member(client_missing.discord_user.id)
            if member:
                description += f'{member.display_name}\n'

    description += f'\n{footer}'

    logging.info(f"Done creating leaderboard.\nDescription:\n{de_emojify(description)}")
    return discord.Embed(
        title='Leaderboard :medal:',
        description=description
    )


async def calc_gains(clients: List[Client],
                     event: db_event.Event,
                     search: datetime,
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

    if currency is None:
        currency = '$'

    results = []
    for client in clients:
        if not client:
            logging.info('calc_gains: A none client was passed in?')
            continue

        # search, _ = dbutils.get_guild_start_end_times(guild_id, search, None, archived=archived)
        #
        # balance_then = user_manager.db_match_balance_currency(
        #    Balance.query.filter(
        #        Balance.client_id == client.id,
        #        Balance.tz_time >= search
        #    ).first(),
        #    currency
        # )

        search, _ = await dbutils.get_guild_start_end_times(event, search, None)
        balance_then = await client.get_balance_at_time(search, currency=currency)
        # balance_then = db_match_balance_currency(
        #    await db_first(
        #        client.history.statement.filter(
        #            Balance.time > search
        #        ).order_by(asc(Balance.time))
        #    ),
        #    currency
        # )

        balance_now = await client.latest()

        # history = await user_manager.get_client_history(client, event, since=search, currency=currency)
        # balance_now = db_match_balance_currency(
        #     await db_first(
        #         client.statement.filter(
        #             Balance.time < search
        #         ).order_by(None).order_by(
        #             desc(Balance.time)
        #         )
        #     ),
        #     currency
        # )

        if balance_then and balance_now:
            # balance_then = history.data[0]
            # balance_now = db_match_balance_currency(history.data[len(history.data) - 1], currency)
            diff = round(balance_now.unrealized - balance_then.unrealized,
                         ndigits=config.CURRENCY_PRECISION.get(currency, 3))

            if balance_then.unrealized > 0:
                results.append(
                    ClientGain(
                        client=client,
                        relative=round(100 * (diff / balance_then.unrealized), ndigits=config.CURRENCY_PRECISION.get('%', 2)),
                        absolute=diff
                    )
                )
            else:
                results.append(
                    ClientGain(client, Decimal(0), diff)
                )
        else:
            results.append(ClientGain(client, None, None))

    return results


def calc_time_from_time_args(time_str: str, allow_future=False) -> Optional[datetime]:
    """
    Calculates time from given time args.
    Arg Format:
      <n><f>
      where <f> can be m (minutes), h (hours), d (days) or w (weeks)

      or valid time string

    :raise:
      ValueError if invalid arg is given
    :return:
      Calculated timedelta or None if None was passed in
    """

    if not time_str:
        return None

    time_str = time_str.lower()

    # Different time formats: True or False indicates whether the date is included.
    formats = [
        (False, "%H:%M:%S"),
        (False, "%H:%M"),
        (False, "%H"),
        (True, "%d.%m.%Y %H:%M:%S"),
        (True, "%d.%m.%Y %H:%M"),
        (True, "%d.%m.%Y %H"),
        (True, "%d.%m.%Y"),
        (True, "%d.%m. %H:%M:%S"),
        (True, "%d.%m. %H:%M"),
        (True, "%d.%m. %H"),
        (True, "%d.%m.")
    ]

    date = None
    now = datetime.now(pytz.utc)
    for includes_date, time_format in formats:
        try:
            date = datetime.strptime(time_str, time_format)
            if not includes_date:
                date = date.replace(year=now.year, month=now.month, day=now.day, microsecond=0)
            elif date.year == 1900:  # %d.%m. not setting year to 1970 but to 1900?
                date = date.replace(year=now.year)
            break
        except ValueError:
            continue

    if not date:
        minute = 0
        hour = 0
        day = 0
        week = 0
        second = 0
        args = time_str.split(' ')
        if len(args) > 0:
            for arg in args:
                try:
                    if 'h' in arg:
                        hour += int(arg.rstrip('h'))
                    elif 'm' in arg:
                        minute += int(arg.rstrip('m'))
                    elif 's' in arg:
                        second += int(arg.rstrip('s'))
                    elif 'w' in arg:
                        week += int(arg.rstrip('w'))
                    elif 'd' in arg:
                        day += int(arg.rstrip('d'))
                    else:
                        raise UserInputError(f'Invalid time argument: {arg}')
                except ValueError:  # Make sure both cases are treated the same
                    raise UserInputError(f'Invalid time argument: {arg}')
        date = now - timedelta(hours=hour, minutes=minute, days=day, weeks=week, seconds=second)

    if not date:
        raise UserInputError(f'Invalid time argument: {time_str}')
    elif date > now and not allow_future:
        raise UserInputError(f'Future dates are not allowed. {time_str}')

    return date


async def call_unknown_function(fn: Callable, *args, **kwargs) -> Any:
    if callable(fn):
        try:
            if inspect.iscoroutinefunction(fn):
                return await fn(*args, **kwargs)
            else:
                res = fn(*args, **kwargs)
                if inspect.isawaitable(res):
                    return await res
                return res
        except Exception:
            print(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )
            logging.exception(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )


def validate_kwargs(kwargs: Dict, required: list[str] | set[str]):
    return len(kwargs.keys()) >= len(required) and all(required_kwarg in kwargs for required_kwarg in required)


def readable_time(time: datetime) -> str:
    """
    Utility for converting a date to a readable format, only showing the date if it's not equal to the current one.
    If None is passed in, the default value 'since start' will be returned
    :param time: Time to convert
    :return: Converted String
    """
    now = datetime.now(pytz.utc)
    if time is None:
        time_str = 'since start'
    else:
        if time.date() == now.date():
            time_str = f'since {time.strftime("%H:%M")}'
        elif time.year == now.year:
            time_str = f'since {time.strftime("%d.%m. %H:%M")}'
        else:
            time_str = f'since {time.strftime("%d.%m.%Y %H:%M")}'

    return time_str


def list_last(l: list, default: Any = None):
    return l[len(l) - 1] if l else default


def db_match_balance_currency(balance: Balance, currency: str):
    return balance

    result = None

    if balance is None:
        return None

    result = None

    if balance.currency != currency:
        if balance.extra_currencies:
            result_currency = balance.extra_currencies.get(currency)
            if not result_currency:
                result_currency = balance.extra_currencies.get(config.CURRENCY_ALIASES.get(currency))
            if result_currency:
                result = Balance(
                    amount=result_currency,
                    currency=currency,
                    time=balance.time
                )
    else:
        result = balance

    return result


def combine_time_series(*time_series: typing.Iterable):
    return sorted(
        itertools.chain.from_iterable(time_series),
        key=lambda a: a.time
    )


def prev_now_next(iterable, skip: Callable = None):
    i = iter(iterable)
    prev = None
    now = next(i, None)
    while now:
        _next = next(i, None)
        if skip and _next and skip(_next):
            continue
        yield prev, now, _next
        prev = now
        now = _next


def join_args(*args, denominator=':'):
    return denominator.join([str(arg.value if isinstance(arg, Enum) else arg) for arg in args if arg])


T = typing.TypeVar('T')


def groupby(items: list[T], key: str | Callable[[T], Any]):
    res = {}
    if isinstance(key, str):
        key = lambda x: getattr(x, key)
    for item in items:
        val = key(item)
        if val not in res:
            res[val] = []
        res[val].append(item)
    return res


def truthy_dict(**kwargs):
    return dict((k, v) for k, v in kwargs.items() if v)


def mask_dict(d, *keys, value_func=None):
    value_func = value_func or (lambda x: x)
    return dict((k, value_func(v)) for k, v in d.items() if k in keys)
