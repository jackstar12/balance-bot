from dataclasses import dataclass
from typing import Tuple, Dict, List, Type, Optional
from datetime import datetime
import sqlalchemy.schema as schema
import sqlalchemy.sql.sqltypes as types


@dataclass
class Trade:
    symbol: str
    price: float
    qty: float
    side: str
    type: str
    time: int
    leverage: int = 1

