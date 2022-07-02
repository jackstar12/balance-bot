from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Dict, Optional

from tradealpha.common.dbmodels.base import OrmBaseModel


class FullBalance(OrmBaseModel):
    realized: Decimal
    unrealized: Decimal
    total_transfered: Decimal
    extra_currencies: Optional[Dict]
    time: datetime


class Amount(NamedTuple):
    amount: Decimal
    time: datetime
