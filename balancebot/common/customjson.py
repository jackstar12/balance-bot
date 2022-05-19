from decimal import Decimal
from typing import Any
import json


def default(obj: Any):
    if isinstance(obj, Decimal):
        return str(obj)
    raise TypeError


def dumps(obj: Any):
    return json.dumps(obj, default=default)


def loads(obj: Any):
    return json.loads(obj, parse_float=Decimal)
