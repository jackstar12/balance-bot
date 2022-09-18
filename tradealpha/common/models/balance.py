from datetime import datetime
from decimal import Decimal
from typing import Optional

from tradealpha.common.models import OrmBaseModel


class Balance(OrmBaseModel):
    time: datetime
    realized: Decimal
    unrealized: Decimal
    total_transfered: Decimal
    extra_currencies: Optional[list]

    @property
    def total_transfers_corrected(self):
        return self.unrealized - self.total_transfered

    def __add__(self, other: 'Balance'):
        return Balance.construct(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            total_transfered=self.total_transfered + other.total_transfered,
            time=min(self.time, other.time) if self.time else None,
            extra_currencies=self.extra_currencies + other.extra_currencies
        )
