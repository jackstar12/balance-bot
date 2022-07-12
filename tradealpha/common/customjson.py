from decimal import Decimal
from typing import Any
import json
import orjson


def default(obj: Any):
    if isinstance(obj, Decimal):
        return str(round(obj, ndigits=3))
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError


def dumps(obj: Any):
    return orjson.dumps(obj, default=default, option=orjson.OPT_OMIT_MICROSECONDS)


def dumps_no_bytes(obj: Any):
    return orjson.dumps(obj, default=default, option=orjson.OPT_OMIT_MICROSECONDS).decode('utf-8')


def loads(obj: Any):
    return json.loads(obj, parse_float=Decimal)
