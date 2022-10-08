from datetime import datetime
from decimal import Decimal
from typing import Optional

from database.models import OutputID
from database.models import OrmBaseModel
from database.dbmodels.transfer import TransferType


class Transfer(OrmBaseModel):
    id: OutputID
    note: Optional[str]
    coin: str
    amount: Decimal
    time: datetime
    commission: Optional[Decimal]
    type: TransferType
    extra_currencies: Optional[dict[str, Decimal]]

