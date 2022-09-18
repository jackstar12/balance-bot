from datetime import date, datetime
from decimal import Decimal
from typing import Any
import json
import orjson
from pydantic import BaseModel

from tradealpha.common import utils


def default(obj: Any):
    if isinstance(obj, Decimal):
        return str(round(obj, ndigits=3))
    if isinstance(obj, tuple):
        return list(obj)
    if isinstance(obj, set):
        return list(obj)
    if isinstance(obj, BaseModel):
        return obj.dict()
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    raise TypeError


def dumps(obj: Any):
    test = orjson.dumps(obj, default=default, option=orjson.OPT_OMIT_MICROSECONDS)
    return test


def dumps_no_bytes(obj: Any):
    return orjson.dumps(obj, default=default, option=orjson.OPT_OMIT_MICROSECONDS).decode('utf-8')


def loads_bytes(obj: Any):
    return orjson.loads(obj)


def loads(obj: Any):
    return json.loads(obj, parse_float=Decimal)
