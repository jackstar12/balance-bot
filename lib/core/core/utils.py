from __future__ import annotations

import asyncio
import functools
import inspect
import itertools
import logging
import operator
import os
import re
import sys
import typing
from asyncio import Task
from datetime import datetime, date, timedelta
from decimal import Decimal
from enum import Enum
from typing import Callable, Union, Dict, Any
from typing import TYPE_CHECKING

import pytz

import core.env as config

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


def utc_now():
    return datetime.now(pytz.utc)


def date_string(d: date | datetime):
    return d.strftime('%Y-%m-%d')


CURRENCY_PRECISION = {
    '$': 2,
    'USD': 2,
    '%': 2,
    'BTC': 6,
    'XBT': 6,
    'ETH': 4
}


def round_ccy(amount: typing.SupportsRound, ccy: str):
    return round(amount, ndigits=CURRENCY_PRECISION.get(ccy, 3))


def weighted_avg(values: tuple[Decimal, Decimal], weights: tuple[Decimal, Decimal]):
    total = weights[0] + weights[1]
    return values[0] * (weights[0] / total) + values[1] * (weights[1] / total)



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


def calc_percentage_diff(then: Union[float, Decimal], diff: Union[float, Decimal]) -> float | str | Decimal:
    num_cls = type(then)
    if diff == 0:
        result = '0'
    elif then > 0:
        result = round(100 * (diff / then), ndigits=3)
    else:
        result = 0
    return num_cls(result)


TIn = typing.TypeVar('TIn')
TOut = typing.TypeVar('TOut')
CoroOrCallable = Union[Callable[[TIn], TOut], Callable[[TIn], typing.Awaitable[TOut]]]


def call_unknown_function(fn: CoroOrCallable, *args, **kwargs):
    if callable(fn):
        try:
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                return asyncio.create_task(res)
        except Exception as e:
            print(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )
            logger.exception(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )
            raise


async def return_unknown_function(fn: CoroOrCallable, *args, **kwargs) -> typing.Optional[Task]:
    if callable(fn):
        try:
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                return await res
            return res
        except Exception as e:
            print(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )
            logger.exception(
                f'Exception occured while execution {fn} {args=} {kwargs=}'
            )
            raise


def validate_kwargs(kwargs: dict, required: list[str] | set[str]):
    return len(kwargs.keys()) >= len(required) and all(required_kwarg in kwargs for required_kwarg in required)


_KT = typing.TypeVar('_KT')
_VT = typing.TypeVar('_VT')


def get_multiple(d: dict[_KT, _VT], *keys: str) -> typing.Optional[_VT]:
    for key in keys:
        if key in d:
            return d[key]


def map_list(func, iter):
    return [func(current) for current in iter]


def get_multiple_dict(key: str, *dicts: dict[_KT, _VT]) -> typing.Optional[_VT]:
    for d in dicts:
        if key in d:
            return d[key]



def parse_isoformat(iso: str):
    return datetime.fromisoformat(iso.replace('Z', '+00:00'))


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
    return l[-1] if l else default


def combine_time_series(*time_series: typing.Iterable):
    return sorted(
        itertools.chain.from_iterable(time_series),
        key=lambda a: a.time
    )


T = typing.TypeVar('T')


def prev_now_next(iterable: typing.Iterable[T], skip: Callable = None):
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


def safe_cmp_default(fnc: Callable[[T, T], T], a: T, b: T):
    return fnc(a, b) if a and b else a or b


def safe_cmp(fnc: Callable[[T, T], T], a: T, b: T):
    return fnc(a, b) if a and b else None


def sum_iter(iterator: typing.Iterable[T]):
    return functools.reduce(operator.add, iterator)


KT = typing.TypeVar('KT')
VT = typing.TypeVar('VT')


def groupby(items: typing.Iterable[VT], key: str | Callable[[VT], KT]) -> dict[KT, list[VT]]:
    res = {}
    if isinstance(key, str):
        def key(x: VT) -> KT:
            return getattr(x, key)
    for item in items:
        val = key(item)
        if val not in res:
            res[val] = []
        res[val].append(item)
    return res


def groupby_unique(items: list[VT], key: str | Callable[[VT], KT]) -> dict[KT, VT]:
    res = {}
    if isinstance(key, str):
        def key(x: VT) -> KT:
            return getattr(x, key)
    for item in items:
        val = key(item)
        res[val] = item
    return res


def truthy_dict(**kwargs):
    return dict((k, v) for k, v in kwargs.items() if v)


def get_timedelta(time_str: str) -> typing.Optional[timedelta]:
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
                    raise ValueError(f'Invalid time argument: {arg}')
            except ValueError:  # Make sure both cases are treated the same
                raise ValueError(f'Invalid time argument: {arg}')
    result = timedelta(hours=hour, minutes=minute, days=day, weeks=week, seconds=second)


    if not result:
        raise ValueError(f'Invalid time argument: {time_str}')

    return result



def mask_dict(d, *keys, value_func=None):
    value_func = value_func or (lambda x: x)
    return dict((k, value_func(v)) for k, v in d.items() if k in keys)
