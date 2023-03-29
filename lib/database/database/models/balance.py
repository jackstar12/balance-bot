from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Optional

from database.models import OrmBaseModel, OutputID, BaseModel
from database.models.gain import Gain
from core.utils import calc_percentage_diff, safe_cmp_default, round_ccy


class AmountBase(OrmBaseModel):
    currency: Optional[str]
    realized: Decimal
    unrealized: Decimal
    client_id: Optional[OutputID]
    rate: Optional[Decimal]

    def _assert_equal(self, other: 'AmountBase'):
        assert self.currency == other.currency

    def gain_since(self, other: 'AmountBase', offset: Decimal) -> Gain:
        self._assert_equal(other)
        gain = (self.total - other.realized) - (offset or 0)
        return Gain.construct(
            absolute=gain,
            relative=calc_percentage_diff(other.realized, gain)
        )

    @property
    def total_transfers_corrected(self):
        return self.unrealized

    @property
    def total(self):
        return self.realized + self.unrealized

    def __repr__(self):
        return f'{self.total}{self.currency}'

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
            time=safe_cmp_default(max, self.time, other.time)
        )


class BalanceGain(BaseModel):
    other: Optional[Balance]
    total: Optional[Gain]
    extra: Optional[list[Gain]]


class Balance(Amount):
    extra_currencies: Optional[list[AmountBase]]
    gain: Optional[BalanceGain]

    def __add__(self, other: Balance):
        self._assert_equal(other)
        return Balance(
            realized=self.realized + other.realized,
            unrealized=self.unrealized + other.unrealized,
            time=safe_cmp_default(max, self.time, other.time),
            extra_currencies=(self.extra_currencies or []) + (other.extra_currencies or []),
            currency=self.currency
        )

    def set_gain(self, other: Balance, offset: Decimal):
        self.gain = BalanceGain(
            other=other,
            total=self.gain_since(other, offset),
        )

    def to_string(self, display_extras=False):
        ccy = self.currency
        string = f'{round_ccy(self.unrealized, ccy)}{ccy}'

        if self.extra_currencies and display_extras:
            currencies = " / ".join(
                f'{amount.unrealized}{amount.currency}'
                for amount in self.extra_currencies
            )
            string += f'({currencies})'

        return string

    def get_currency(self, currency: Optional[str]) -> Balance:
        if currency:
            for amount in self.extra_currencies:
                if amount.currency == currency:
                    return Balance(
                        realized=amount.realized,
                        unrealized=amount.unrealized,
                        currency=currency,
                        time=self.time
                    )
        else:
            return self


BalanceGain.update_forward_refs()
