from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Dict, NamedTuple, Optional, Any, Tuple

from pydantic import BaseModel, Field, Extra

from tradealpha.api.models.execution import Execution
from tradealpha.api.models.trade import Trade
from tradealpha.common.enums import Filter
from tradealpha.common.models.pnldata import PnlData as CompactPnlData



class Calculation(Enum):
    PNL = "pnl"
    WINRATE = "winrate"


class PnlData(BaseModel):
    time: datetime
    realized: Decimal
    unrealized: Decimal

    class Config:
        orm_mode = True


class TradeAnalytics(Trade):
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


class Performance(NamedTuple):
    relative: Decimal
    absolute: Decimal
    #filter_values: Dict[Filter, Any]
    filter_values: List[Any]


class FilteredPerformance(BaseModel):
    filters: Tuple[Filter, ...]
    performances: List[Performance]


class ClientAnalytics(BaseModel):
    id: int
    filtered_performance: FilteredPerformance
    trades: List[TradeAnalytics]
