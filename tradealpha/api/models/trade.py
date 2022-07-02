from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel

from tradealpha.api.models.execution import Execution
from tradealpha.common.enums import Side, Status


class Trade(BaseModel):
    id: str
    client_id: str
    symbol: str
    entry: Decimal
    exit: Optional[Decimal]
    side: Side
    status: Status

    transferred_qty: Decimal
    qty: Decimal
    open_qty: Decimal
    realized_pnl: Decimal
    executions: List[Execution]
    label_ids: List[str]
    open_time: datetime
    close_time: datetime
    #initial: Execution
    #initial_execution_id: int

    class Config:
        orm_mode = True

