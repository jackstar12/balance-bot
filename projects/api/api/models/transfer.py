from datetime import datetime
from decimal import Decimal
from typing import Optional

from common.models import OutputID
from common.models import OrmBaseModel
from common.dbmodels.transfer import TransferType


class Transfer(OrmBaseModel):
    id: OutputID
    note: Optional[str]
    coin: str
    amount: Decimal
    time: datetime
    commission: Optional[Decimal]
    type: TransferType
    extra_currencies: Optional[dict[str, Decimal]]

