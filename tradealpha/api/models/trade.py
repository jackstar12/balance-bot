from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import Field, Extra

from tradealpha.common.models.document import DocumentModel
from tradealpha.common.models.balance import Balance
from tradealpha.api.models import OutputID
from tradealpha.api.models.pnldata import PnlData
from tradealpha.common.models import OrmBaseModel, BaseModel, InputID
from tradealpha.api.models.execution import Execution
from tradealpha.common.enums import Side, Status, TradeSession
from tradealpha.common.models.compactpnldata import CompactPnlData


class BasicTrade(OrmBaseModel):
    id: OutputID
    client_id: str
    symbol: str
    entry: Decimal
    exit: Optional[Decimal]
    side: Side
    status: Status
    transferred_qty: Decimal
    total_commissions: Optional[Decimal]
    qty: Decimal
    open_qty: Decimal
    realized_pnl: Decimal
    open_time: datetime
    close_time: Optional[datetime]
    weekday: int


class Trade(BasicTrade):
    executions: List[Execution]
    label_ids: List[str]
    #initial: Execution
    #initial_execution_id: int



class DetailledTrade(Trade):
    tp: Optional[Decimal]
    sl: Optional[Decimal]

    init_balance: Optional[Balance]
    max_pnl: Optional[PnlData]
    min_pnl: Optional[PnlData]
    sessions: list[TradeSession]

    fomo_ratio: Optional[Decimal]
    greed_ratio: Optional[Decimal]
    risk_to_reward: Optional[Decimal]
    realized_r: Optional[Decimal]
    account_size_init: Optional[Decimal]
    account_gain: Optional[Decimal]
    notes: Optional[DocumentModel]

    class Config:
        orm_mode = True
        arbitrary_types_allowed = False
        extra = Extra.ignore


class LabelUpdate(BaseModel):
    group_ids: set[InputID]
    label_ids: set[InputID]


class UpdateTrade(BaseModel):
    labels: Optional[LabelUpdate]
    notes: Optional[DocumentModel]
