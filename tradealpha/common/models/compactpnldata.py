from decimal import Decimal
from typing import NamedTuple


class CompactPnlData(NamedTuple):
    ts: int
    realized: Decimal
    unrealized: Decimal
