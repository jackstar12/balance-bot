from datetime import datetime
from decimal import Decimal

from common.models import BaseModel


class PnlData(BaseModel):
    time: datetime
    realized: Decimal
    unrealized: Decimal

    class Config:
        orm_mode = True
