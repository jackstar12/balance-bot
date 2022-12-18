from decimal import Decimal
from typing import NamedTuple

from database.dbmodels.client import ExchangeInfo


class Ticker(NamedTuple):

    symbol: str
    src: ExchangeInfo
    price: Decimal
