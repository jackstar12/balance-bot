from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from database.enums import IntervalType
from database.models import BaseModel
from database.models.balance import Amount
from database.models.gain import Gain


class Interval(BaseModel):
    day: date
    length: Optional[IntervalType]
    gain: Gain
    start_balance: Amount
    end_balance: Amount
    offset: Decimal

    class Config:
        orm_mode = True

    @classmethod
    def create(cls, prev: Amount, current: Amount, offset: Decimal, length: IntervalType = None) -> Interval:
        return cls(
            day=current.time.date(),
            gain=current.gain_since(prev, offset),
            start_balance=prev,
            end_balance=current,
            offset=offset,
            length=length
        )

    def __add__(self, other):
        return self.create(
            self.start_balance + other.start_balance,
            self.end_balance + other.end_balance,
            offset=self.offset + other.offset
        )
