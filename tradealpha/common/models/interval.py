from __future__ import annotations
from decimal import Decimal
from typing import NamedTuple, Union
from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING

from tradealpha.common.models.gain import Gain
from tradealpha.common.models import BaseModel
from tradealpha.common.models.balance import Amount


class Interval(BaseModel):
    day: date
    gain: Gain
    start_balance: Amount
    end_balance: Amount
    offset: Decimal

    class Config:
        orm_mode = True

    @classmethod
    def create(cls, prev: Amount, current: Amount, offset: Decimal) -> Interval:
        if not hasattr(current, 'time'):
            pass
        return cls(
            day=current.time,
            gain=current.gain_since(prev, offset),
            start_balance=prev,
            end_balance=current,
            offset=offset
        )

    def __add__(self, other):
        return self.create(
            self.start_balance + other.start_balance,
            self.end_balance + other.end_balance,
            offset=self.offset + other.offset
        )
