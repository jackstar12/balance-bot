from decimal import Decimal
from typing import NamedTuple

from tradealpha.common.models import BaseModel


class CompactPnlData(NamedTuple):
    ts: int
    realized: Decimal
    unrealized: Decimal
