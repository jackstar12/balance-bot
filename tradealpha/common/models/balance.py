from datetime import datetime
from decimal import Decimal
from typing import Optional

from common.utils import calc_percentage, calc_percentage_diff
from tradealpha.common.models import OrmBaseModel


class AmountBase(OrmBaseModel):
    currency: Optional[str]
    realized: Decimal
    unrealized: Decimal
    total_transfered: Decimal

    def gain_since(self, other: 'Amount'):
        gain = (self.realized - other.realized) - (self.total_transfered - other.total_transfered)
        return gain, calc_percentage_diff(self.realized, gain)

    @property
    def total_transfers_corrected(self):
        return self.unrealized - self.total_transfered

    def __add__(self, other: 'Amount'):
        return Amount.construct(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            total_transfered=self.total_transfered + other.total_transfered,
        )


class Amount(AmountBase):
    time: datetime


class Balance(OrmBaseModel, Amount):
    extra_currencies: Optional[list[AmountBase]]

    def __add__(self, other: 'Balance'):
        return Balance.construct(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            total_transfered=self.total_transfered + other.total_transfered,
            time=min(self.time, other.time) if self.time else None,
            extra_currencies=[self.extra_currencies + other.extra_currencies]
        )
