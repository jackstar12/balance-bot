from datetime import datetime
from decimal import Decimal
from typing import NamedTuple


class Amount(NamedTuple):
    amount: Decimal
    time: datetime
