import typing
from datetime import datetime
from decimal import Decimal


class Balance(typing.Protocol):
    time: datetime
    realized: Decimal
    unrealized: Decimal
    extra_currencies: typing.Optional[list]
    currency: str

    @property
    def total_transfers_corrected(self):
        return self.unrealized


    @property
    def total(self):
        return self.realized + self.unrealized
