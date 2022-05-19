from datetime import datetime
from decimal import Decimal
from typing import NamedTuple


class OHLC(NamedTuple):
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    time: datetime
