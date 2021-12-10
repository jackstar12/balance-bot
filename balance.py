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



