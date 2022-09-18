from __future__ import annotations
from decimal import Decimal
from typing import NamedTuple, Union
from datetime import datetime, date, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel

from tradealpha.common.models.balance import Balance


class Interval(BaseModel):
    day: Union[date, str]
    diff_absolute: Decimal
    diff_relative: Decimal
    start_balance: Balance
    end_balance: Balance

    class Config:
        orm_mode = True

    @classmethod
    def create(cls, prev: Balance, current: Balance, as_string=False) -> Interval:
        current_date = current.time
        gain = (current.realized - prev.realized) - (current.total_transfered - prev.total_transfered)
        return cls(
            day=current_date.strftime('%Y-%m-%d') if as_string else current_date,
            diff_absolute=gain,
            diff_relative=100 * (gain / prev.realized),
            start_balance=prev,
            end_balance=current
        )

    def __add__(self, other):
        return self.create(
            self.start_balance + other.start_balance,
            self.end_balance + other.end_balance
        )
