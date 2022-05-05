import enum
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.common.database import Base
from balancebot.common.dbmodels.amountmixin import AmountMixin


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
