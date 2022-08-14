from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class MiscIncome:
    amount: Decimal
    time: datetime
