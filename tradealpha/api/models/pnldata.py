from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class PnlData(BaseModel):
    time: datetime
    realized: Decimal
    unrealized: Decimal

    class Config:
        orm_mode = True
