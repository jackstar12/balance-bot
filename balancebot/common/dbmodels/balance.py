import logging
from datetime import datetime
from decimal import Decimal

import pytz
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from typing_extensions import Self

from balancebot.common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, Numeric, DateTime, orm

import balancebot.common.config as config
from balancebot.common.dbmodels.amountmixin import AmountMixin
from balancebot.common.dbmodels.serializer import Serializer


class Balance(Base, Serializer):
    __tablename__ = 'balance'
    __serializer_forbidden__ = ['id', 'error', 'client_id', 'client', 'transfer', 'transfer_id']

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('client.id', ondelete="CASCADE"), nullable=True)
    client = relationship('Client', foreign_keys=client_id)
    time = Column(DateTime(timezone=True), nullable=False, index=True)

    realized: Decimal = Column(Numeric, nullable=False, default=Decimal(0))
    unrealized: Decimal = Column(Numeric, nullable=False, default=Decimal(0))
    total_transfered: Decimal = Column(Numeric, nullable=False, default=Decimal(0))
    extra_currencies = Column(JSONB, nullable=True)

    transfer_id = Column(Integer, ForeignKey('transfer.id', ondelete='SET NULL'), nullable=True)
    transfer = relationship('Transfer')

    @hybrid_property
    def total(self):
        return self.unrealized

    @hybrid_property
    def total_transfers_corrected(self):
        return self.unrealized - self.total_transfered

    # Backwards compatability
    @hybrid_property
    def amount(self):
        return self.unrealized

    def __eq__(self, other):
        return self.realized == other.realized and self.unrealized == other.unrealized

    def __init__(self, error=None, *args, **kwargs):
        self.error = error
        super().__init__(*args, **kwargs)

    @orm.reconstructor
    def reconstructor(self):
        self.error = None

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
        string = f'{round(self.amount, ndigits=config.CURRENCY_PRECISION.get("$", 3))}"$"'

        if self.extra_currencies and display_extras:
            first = True
            for currency in self.extra_currencies:
                string += f'{" (" if first else "/"}{self.extra_currencies[currency]}{currency}'
                first = False
            if not first:
                string += ')'

        return string

    @classmethod
    def is_data(cls):
        return True

    async def serialize(self, data=True, full=True, *args, **kwargs):
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
        else:
            return await super().serialize(full=False, data=True)

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
