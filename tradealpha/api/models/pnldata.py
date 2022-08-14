from datetime import datetime
from decimal import Decimal

from tradealpha.api.models import BaseModel


class PnlData(BaseModel):
    time: datetime
    realized: Decimal
    unrealized: Decimal

    class Config:
        orm_mode = True
