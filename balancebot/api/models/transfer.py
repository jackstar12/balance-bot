from datetime import datetime
from decimal import Decimal

from common.dbmodels.base import OrmBaseModel


class Transfer(OrmBaseModel):

    note: str
    coin: str
    commission: Decimal
    amount: Decimal
    time: datetime
    extra_currencies: dict[str, Decimal]
