from datetime import datetime
from typing import NamedTuple

from balancebot.common.enums import Side


class Trade(NamedTuple):

    symbol: str
    side: str
    size: float
    price: float
    exchange: str
    time: datetime
    perp: bool
