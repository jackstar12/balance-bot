from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from balancebot.common.enums import ExecType, Side


class Execution(BaseModel):
    symbol: str
    price: Decimal
    qty: Decimal
    side: Side
    time: datetime
    type: ExecType
    commission: Decimal
    realized_pnl: Decimal
