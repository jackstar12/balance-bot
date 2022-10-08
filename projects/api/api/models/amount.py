from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Dict, Optional


class Amount(NamedTuple):
    amount: Decimal
    time: datetime
