from typing import List

from pydantic import BaseModel


class TradeAnalytics(BaseModel):
    id: int


class ClientAnalytics(BaseModel):
    id: int

    trades: List[TradeAnalytics]
