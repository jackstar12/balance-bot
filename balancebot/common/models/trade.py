from datetime import datetime
from decimal import Decimal
from typing import NamedTuple

from balancebot.common.enums import Side


class Trade(NamedTuple):

    symbol: str
    side: str
    size: Decimal
    price: Decimal
    exchange: str
    time: datetime
    perp: bool
