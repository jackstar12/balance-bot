from datetime import datetime
from decimal import Decimal
from typing import Optional

from tradealpha.api.models import OutputID
from tradealpha.common.models import OrmBaseModel
from tradealpha.common.dbmodels.transfer import TransferType


class Transfer(OrmBaseModel):
    id: OutputID
    note: Optional[str]
    coin: str
    amount: Decimal
    time: datetime
    commission: Optional[Decimal]
    type: TransferType
    extra_currencies: Optional[dict[str, Decimal]]

