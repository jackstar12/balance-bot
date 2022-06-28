from datetime import datetime
from decimal import Decimal
from typing import Optional

from balancebot.common.dbmodels.base import OrmBaseModel
from balancebot.common.dbmodels.transfer import TransferType


class Transfer(OrmBaseModel):
    id: str
    note: Optional[str]
    coin: str
    commission: Optional[Decimal]
    type: TransferType
    extra_currencies: dict[str, Decimal]

