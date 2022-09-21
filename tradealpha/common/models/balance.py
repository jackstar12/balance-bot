from datetime import datetime
from decimal import Decimal
from typing import Optional

from tradealpha.common.utils import calc_percentage, calc_percentage_diff
from tradealpha.common.models import OrmBaseModel


class AmountBase(OrmBaseModel):
    currency: Optional[str]
    realized: Decimal
    unrealized: Decimal

    def _assert_equal(self, other: 'AmountBase'):
        assert self.currency == other.currency

    def gain_since(self, other: 'AmountBase', offset: Decimal):
        self._assert_equal(other)
        gain = (self.realized - other.realized) - offset
        return gain, calc_percentage_diff(self.realized, gain)

    @property
    def total_transfers_corrected(self):
        return self.unrealized

    def __add__(self, other: 'AmountBase'):
        self._assert_equal(other)
        return AmountBase(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            currency=self.currency,
        )


class Amount(AmountBase):
    time: datetime

    def __add__(self, other: 'Amount'):
        self._assert_equal(other)
        return Amount(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            currency=self.currency,
            time=self.time
        )


class Balance(Amount):
    extra_currencies: Optional[list[AmountBase]]

    def __add__(self, other: 'Balance'):
        return Balance(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            time=min(self.time, other.time) if self.time else None,
            extra_currencies=(self.extra_currencies or []) + (other.extra_currencies or [])
        )
