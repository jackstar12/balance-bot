from decimal import Decimal
from typing import NamedTuple


class PnlData(NamedTuple):
    ts: int
    realized: Decimal
    unrealized: Decimal
