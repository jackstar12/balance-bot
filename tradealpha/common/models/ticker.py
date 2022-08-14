from decimal import Decimal
from typing import NamedTuple


class Ticker(NamedTuple):

    symbol: str
    exchange: str
    price: Decimal
