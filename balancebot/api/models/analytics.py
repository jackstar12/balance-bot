from decimal import Decimal
from enum import Enum
from typing import List, Dict, NamedTuple, Optional, Any, Tuple

from pydantic import BaseModel

from balancebot.api.models.execution import Execution
from balancebot.api.models.trade import Trade
from balancebot.common.enums import Filter


class Calculation(Enum):
    PNL = "pnl"
    WINRATE = "winrate"


class PnlData(BaseModel):
    realized: Decimal
    unrealized: Decimal


class TradeAnalytics(Trade):
    tp: Optional[Decimal]
    sl: Optional[Decimal]

    max_pnl: PnlData
    min_pnl: PnlData
    # order_count: int

    executions: List[Execution]
    pnl_data: List[PnlData]

    fomo_ratio: Decimal
    greed_ratio: Decimal
    risk_to_reward: Optional[Decimal]
    realized_r: Optional[Decimal]
    memo: Optional[str]

    class Config:
        orm_mode = True
        arbitrary_types_allowed = False


class Performance(NamedTuple):
    relative: Decimal
    absolute: Decimal
    filter_values: Dict[Filter, Any]


class FilteredPerformance(BaseModel):
    filters: Tuple[Filter, ...]
    performances: List[Performance]


class ClientAnalytics(BaseModel):
    id: int
    filtered_performance: FilteredPerformance
    trades: List[TradeAnalytics]
