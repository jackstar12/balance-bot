import enum
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Dict, Optional

import sqlalchemy as sa
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType, Table, BigInteger, Numeric
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base, Meta
from balancebot.api.dbmodels.amountmixin import AmountMixin


class Type(enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


class RawTransfer(NamedTuple):
    amount: float
    time: datetime
    coin: str


class Transfer(Base, AmountMixin):
    __tablename__ = 'transfer'

    id = Column(BigInteger, primary_key=True)
    client_id = Column(
        Integer,
        ForeignKey('client.id', ondelete="CASCADE"),
        nullable=False
    )
    note = Column(String, nullable=True)

    balance = relationship(
        'Balance',
        lazy='joined',
        uselist=False,
        backref=backref('transfer', lazy='joined')
    )

    @hybrid_property
    def type(self) -> Type:
        return Type.DEPOSIT if self.amount > 0 else Type.WITHDRAW
