from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel

from balancebot.api.models.execution import Execution
from balancebot.common.enums import Side


class Trade(BaseModel):
    id: int

    symbol: str
    entry: Decimal
    exit: Optional[Decimal]

    transferred_qty: Decimal
    qty: Decimal
    open_qty: Decimal
    realized_pnl: Decimal

    labels: List[int]
    #initial: Execution
    initial_execution_id: int

