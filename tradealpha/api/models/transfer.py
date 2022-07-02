from datetime import datetime
from decimal import Decimal
from typing import Optional

from tradealpha.common.dbmodels.base import OrmBaseModel
from tradealpha.common.dbmodels.transfer import TransferType


class Transfer(OrmBaseModel):
    id: str
    note: Optional[str]
    coin: str
    commission: Optional[Decimal]
    type: TransferType
    extra_currencies: Optional[dict[str, Decimal]]

