from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from tradealpha.common.enums import ExecType, Side


class Execution(BaseModel):
    symbol: str
    price: Decimal
    qty: Decimal
    side: Side
    time: datetime
    type: Optional[ExecType] = Field(default=ExecType.TRADE)
    commission: Optional[Decimal]
    realized_pnl: Optional[Decimal]

    class Config:
        orm_mode = True
