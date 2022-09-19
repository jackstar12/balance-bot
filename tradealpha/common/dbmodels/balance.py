from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytz
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from tradealpha.common.dbmodels.mixins.querymixin import QueryMixin
from tradealpha.common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, Numeric, DateTime, orm

import tradealpha.common.config as config
from tradealpha.common.dbmodels.mixins.serializer import Serializer
import sqlalchemy as sa
from tradealpha.common.models.balance import Amount as AmountModel

if TYPE_CHECKING:
    from tradealpha.common.dbmodels import Client


class _Common:
    realized: Decimal = Column(Numeric, nullable=False, default=Decimal(0))
    unrealized: Decimal = Column(Numeric, nullable=False, default=Decimal(0))
    total_transfered: Decimal = Column(Numeric, nullable=False, default=Decimal(0))


class Amount(Base, Serializer, _Common):
    __tablename__ = 'amount'

    balance_id = Column(ForeignKey('balance.id', ondelete="CASCADE"), primary_key=True)
    balance = relationship('Balance', lazy='raise')
    currency: str = Column(sa.String(length=3), primary_key=True)


class Balance(Base, _Common, Serializer, QueryMixin):
    """
    Represents the balance of a client at a given time.

    It is divided into mulitple Amount objects.
    The 'realized' field contains the total currently realized equity
    The 'unrealized' field contains the total current equity including unrealized pnl

    If the balance consists of multiple currencies, these are stored in detail in the Amount table (
    """
    __tablename__ = 'balance'
    __serializer_forbidden__ = ['id', 'error', 'client', 'transfer', 'transfer_id']

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey('client.id', ondelete="CASCADE"), nullable=True)
    client: 'Client' = relationship('Client', lazy='raise', foreign_keys=client_id)
    time = Column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies: list[Amount] = relationship('Amount', lazy='noload', back_populates='balance')
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

    def get_currency(self, currency: str) -> AmountModel:
        for amount in self.extra_currencies:
            if amount.currency == currency:
                return AmountModel.from_orm(amount)
        return AmountModel(
            realized=self.realized,
            unrealized=self.unrealized,
            currency=self.client.currency,
            total_transfered=self.total_transfered,
            time=self.time
        )

    def get_realized(self, currency: str) -> Decimal:
        amount = self.get_currency(currency)
        return amount.realized if amount else self.realized

    def get_unrealized(self, currency: str) -> Decimal:
        amount = self.get_currency(currency)
        return amount.unrealized if amount else self.unrealized

    def __eq__(self, other):
        return self.realized == other.realized and self.unrealized == other.unrealized

    def __init__(self, error=None, *args, **kwargs):
        self.error = error
        super().__init__(*args, **kwargs)

    @orm.reconstructor
    def reconstructor(self):
        self.error = None

    def to_string(self, display_extras=False):
        string = f'{round(self.amount, ndigits=config.CURRENCY_PRECISION.get("$", 3))}USD'

        if self.extra_currencies and display_extras:
            currencies = " / ".join(
                f'{amount.unrealized}{amount.currency}'
                for amount in self.extra_currencies
            )
            string += f'({currencies})'

        return string

    def __repr__(self):
        return self.to_string(display_extras=False)

    @classmethod
    def is_data(cls):
        return True

