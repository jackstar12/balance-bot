from dataclasses import dataclass
from typing import Tuple, Dict, List, Type, Optional


@dataclass
class Trade:
    symbol: str
    price: float
    qty: float
    side: str
    type: str
    leverage: int = 1
