from __future__ import annotations
from decimal import Decimal
from typing import NamedTuple, Union
from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING

from common.models.gain import Gain
from common.models import BaseModel
from common.models.balance import Amount


class Interval(BaseModel):
    day: Union[date, str]
    gain: Gain
    start_balance: Amount
    end_balance: Amount
    offset: Decimal

    class Config:
        orm_mode = True

    @classmethod
    def create(cls, prev: Amount, current: Amount, offset: Decimal, as_string=False) -> Interval:
        if not hasattr(current, 'time'):
            pass
        current_date = current.time
        return cls(
            day=current_date.strftime('%Y-%m-%d') if as_string else current_date,
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
