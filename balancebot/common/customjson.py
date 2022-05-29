from decimal import Decimal
from typing import Any, NamedTuple
import json
import orjson
from fastapi.encoders import jsonable_encoder

from balancebot.common.models.pnldata import PnlData


def default(obj: Any):
    if isinstance(obj, Decimal):
        return str(round(obj, ndigits=3))
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError


def dumps(obj: Any):
    return orjson.dumps(obj, default=default)


def dumps_no_bytes(obj: Any):
    return orjson.dumps(obj, default=default).decode('utf-8')


def loads(obj: Any):
    return json.loads(obj, parse_float=Decimal)
