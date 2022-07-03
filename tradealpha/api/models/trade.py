from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, Extra

from tradealpha.api.models.pnldata import PnlData
from tradealpha.common.dbmodels.base import OrmBaseModel
from tradealpha.api.models.execution import Execution
from tradealpha.common.enums import Side, Status
from tradealpha.common.models.compactpnldata import CompactPnlData


class BasicTrade(OrmBaseModel):
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
    open_time: datetime
    close_time: datetime


class Trade(BasicTrade):
    executions: List[Execution]
    label_ids: List[str]
    #initial: Execution
    #initial_execution_id: int


class DetailledTrade(Trade):
    tp: Optional[Decimal]
    sl: Optional[Decimal]

    max_pnl: Optional[PnlData]
    min_pnl: Optional[PnlData]
    # order_count: int

    pnl_history: List[CompactPnlData] = Field(alias="compact_pnl_data")
    #pnl_data: List[PnlData]

    fomo_ratio: Optional[Decimal]
    greed_ratio: Optional[Decimal]
    risk_to_reward: Optional[Decimal]
    realized_r: Optional[Decimal]
    account_size_init: Optional[Decimal]
    account_gain: Optional[Decimal]
    memo: Optional[str]

    class Config:
        orm_mode = True
        arbitrary_types_allowed = False
        extra = Extra.ignore


