from datetime import datetime
from decimal import Decimal
from typing import NamedTuple


class OHLC(NamedTuple):
    open: float
    high: float
    low: float
    close: float
    volume: float
    time: datetime
