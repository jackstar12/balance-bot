from datetime import datetime

import pytz
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType

from balancebot.bot import config
from balancebot.api.dbmodels.serializer import Serializer


class Balance(Base, Serializer):
    __tablename__ = 'balance'
    __serializer_forbidden__ = ['id', 'error', 'client_id']

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('client.id', ondelete="CASCADE"), nullable=True)
    time: DateTime = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    error = Column(String, nullable=True)
    extra_currencies = Column(PickleType, nullable=True)

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
        string = f'{round(self.amount, ndigits=config.CURRENCY_PRECISION.get(self.currency, 3))}{self.currency}'

        if self.extra_currencies and display_extras:
            first = True
            for currency in self.extra_currencies:
                string += f'{" (" if first else "/"}{round(self.extra_currencies[currency], ndigits=config.CURRENCY_PRECISION.get(currency, 3))}{currency}'
                first = False
            if not first:
                string += ')'

        return string

    def is_data(self):
        return True

    def serialize(self, data=True, full=True, *args, **kwargs):
        currency = kwargs.get('currency', '$')
        if data:
            if currency == '$':
                amount = self.amount
            elif self.extra_currencies:
                amount = self.extra_currencies.get(currency)
            else:
                amount = None
            if amount:
                return (
                    round(amount, ndigits=config.CURRENCY_PRECISION.get(currency, 3)),
                    round(self.time.timestamp() * 1000)
                )

    @hybrid_property
    def tz_time(self, tz=pytz.UTC):
        return self.time.replace(tzinfo=tz)


def balance_from_json(data: dict, time: datetime):
    currency = data.get('currency', '$')
    return Balance(
        amount=round(data.get('amount', 0), ndigits=config.CURRENCY_PRECISION.get(currency, 3)),
        currency=currency,
        extra_currencies=data.get('extra_currencies', None),
        time=time
    )
