from datetime import datetime

from pydantic import BaseModel


class Trade(BaseModel):

    symbol: str
    side: str
    size: float
    price: float
    exchange: str
    time: datetime
    perp: bool
