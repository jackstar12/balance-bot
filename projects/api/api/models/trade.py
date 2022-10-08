from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import Extra

from common.models.document import DocumentModel
from common.models.balance import Balance
from api.models.pnldata import PnlData
from api.models.execution import Execution
from common.models import OrmBaseModel, BaseModel, InputID, OutputID
from common.enums import Side, Status, TradeSession
from common.models.compactpnldata import CompactPnlData


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
    # order_count: int
    sessions: list[TradeSession]
    pnl_history: List[CompactPnlData]
    #pnl_data: List[PnlData]

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


class UpdateTrade(BaseModel):
    label_ids: Optional[list[InputID]]
    notes: Optional[DocumentModel]

