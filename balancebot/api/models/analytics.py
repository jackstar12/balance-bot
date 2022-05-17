from decimal import Decimal
from typing import List, Dict, TypeVar, NamedTuple, Optional, Any, Tuple

from pydantic import BaseModel

from balancebot.api.models.execution import Execution
from balancebot.api.models.trade import Trade
from balancebot.common.enums import Filter, Side
import balancebot.api.models as models

T = TypeVar('T')


class PnlData(NamedTuple):
    realized: Decimal
    unrealized: Decimal


class TradeAnalytics(Trade):
    tp = Optional[Decimal]
    sl = Optional[Decimal]

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


class Performance(NamedTuple):
    relative: Decimal
    absolute: Decimal
    filter_values: Dict[Filter, Any]


class FilteredPerformance(BaseModel):
    filters: Tuple[Filter, ...]
    performance: List[Performance]


class ClientAnalytics(BaseModel):
    id: int
    filtered_performance: FilteredPerformance
    trades: List[TradeAnalytics]
