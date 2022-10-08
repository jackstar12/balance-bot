from datetime import datetime
from decimal import Decimal
from typing import Optional

from database.dbasync import safe_op
from common import config
from database.models import OrmBaseModel, OutputID
from database.models.gain import Gain
from utils import calc_percentage_diff, safe_cmp


class AmountBase(OrmBaseModel):
    currency: Optional[str]
    realized: Decimal
    unrealized: Decimal
    client_id: Optional[OutputID]

    def _assert_equal(self, other: 'AmountBase'):
        assert self.currency == other.currency

    def gain_since(self, other: 'AmountBase', offset: Decimal) -> Gain:
        self._assert_equal(other)
        gain = (self.realized - other.realized) - (offset or 0)
        return Gain(
            absolute=gain,
            relative=calc_percentage_diff(other.realized, gain)
        )

    @property
    def total_transfers_corrected(self):
        return self.unrealized

    def __add__(self, other: 'AmountBase'):
        self._assert_equal(other)
        return AmountBase(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            currency=self.currency
        )


class Amount(AmountBase):
    time: datetime

    def __add__(self, other: 'Amount'):
        self._assert_equal(other)
        return Amount(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            currency=self.currency,
            time=safe_cmp(max, self.time, other.time)
        )


class Balance(Amount):
    extra_currencies: Optional[list[AmountBase]]

    def __add__(self, other: 'Balance'):
        self._assert_equal(other)
        return Balance(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            time=safe_cmp(max, self.time, other.time),
            extra_currencies=(self.extra_currencies or []) + (other.extra_currencies or []),
            currency=self.currency
        )

    def to_string(self, display_extras=False):
        ccy = self.currency
        string = f'{round(self.unrealized, ndigits=config.CURRENCY_PRECISION.get(ccy, 3))}{ccy}'

        if self.extra_currencies and display_extras:
            currencies = " / ".join(
                f'{amount.unrealized}{amount.currency}'
                for amount in self.extra_currencies
            )
            string += f'({currencies})'

        return string


    def get_currency(self, currency: str):
        if currency == self.currency:
            return self
        for amount in self.extra_currencies:
            if amount.currency == currency:
                return amount
