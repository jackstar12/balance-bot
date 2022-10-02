from decimal import Decimal
from enum import Enum
from typing import List, NamedTuple, Any, Tuple

from tradealpha.api.models import BaseModel, OutputID
from tradealpha.api.models.trade import DetailledTrade
from tradealpha.common.enums import Filter


class Calculation(Enum):
    PNL = "pnl"
    WINRATE = "winrate"



class Performance(NamedTuple):
    relative: Decimal
    absolute: Decimal
    #filter_values: Dict[Filter, Any]
    filter_values: List[Any]


class FilteredPerformance(BaseModel):
    filters: Tuple[Filter, ...]
    performances: List[Performance]


class ClientAnalytics(BaseModel):
    id: OutputID
    filtered_performance: FilteredPerformance
    trades: List[DetailledTrade]
