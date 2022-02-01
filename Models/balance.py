from dataclasses import dataclass
from typing import List, Tuple, Dict
import logging
from config import CURRENCY_PRECISION


def balance_from_json(data: dict):
    currency = data.get('currency', '$')
    return Balance(
        amount=round(data.get('amount', 0), ndigits=CURRENCY_PRECISION.get(currency, 3)),
        currency=currency,
        extra_currencies=data.get('extra_currencies', None)
    )


@dataclass
class Balance:
    amount: float
    currency: str
    error: str = None
    extra_currencies: Dict[str, float] = None

    def to_json(self, currency=False):
        json = {
            'amount': self.amount,
        }
        if self.error:
            json['error'] = self.error
        if currency or self.currency != '$':
            json['currency'] = self.currency
        if self.extra_currencies:
            json['extra_currencies'] = self.extra_currencies
        return json

    def to_string(self, display_extras=True):
        string = f'{round(self.amount, ndigits=CURRENCY_PRECISION.get(self.currency, 3))}{self.currency}'

        if self.extra_currencies and display_extras:
            first = True
            for currency in self.extra_currencies:
                string += f' {"(" if first else "/"}{round(self.extra_currencies[currency], ndigits=CURRENCY_PRECISION.get(currency, 3))}{currency}'
                first = False
            if not first:
                string += ')'

        return string



