from __future__ import annotations

import inspect
import itertools
import logging
import os
import re
import sys
import typing
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Callable, Union, Dict, Any
from typing import TYPE_CHECKING

import pytz

import tradealpha.common.config as config

if TYPE_CHECKING:
    pass


def utc_now():
    return datetime.now(pytz.utc)


def date_string(d: date | datetime):
    return d.strftime('%Y-%m-%d')


def round_ccy(amount: typing.SupportsRound, ccy: str):
    return round(amount, ndigits=config.CURRENCY_PRECISION.get(ccy, 3))


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


async def call_unknown_function(fn: CoroOrCallable, *args, **kwargs) -> Any:
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
    return l[-1] if l else default


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


def groupby(items: list[T], key: str | Callable[[T], Any]) -> dict[Any, list[T]]:
    res = {}
    if isinstance(key, str):
        key = lambda x: getattr(x, key)
    for item in items:
        val = key(item)
        if val not in res:
            res[val] = []
        res[val].append(item)
    return res


def groupby_unique(items: list[T], key: str | Callable[[T], Any]) -> dict[Any, T]:
    res = {}
    if isinstance(key, str):
        key_func = lambda x: getattr(x, key)
    else:
        key_func = key
    for item in items:
        val = key_func(item)
        res[val] = item
    return res


def truthy_dict(**kwargs):
    return dict((k, v) for k, v in kwargs.items() if v)


def mask_dict(d, *keys, value_func=None):
    value_func = value_func or (lambda x: x)
    return dict((k, value_func(v)) for k, v in d.items() if k in keys)
