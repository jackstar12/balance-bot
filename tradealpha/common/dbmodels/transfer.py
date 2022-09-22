import enum
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Optional

from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from tradealpha.common.dbsync import Base
from tradealpha.common.dbmodels.mixins.amountmixin import AmountMixin


class TransferType(enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


class RawTransfer(NamedTuple):
    amount: Decimal
    time: datetime
    coin: str
    fee: Optional[Decimal]


class Transfer(Base, AmountMixin):
    __tablename__ = 'transfer'

    id = Column(BigInteger, primary_key=True)
    client_id = Column(
        Integer,
        ForeignKey('client.id', ondelete="CASCADE"),
        nullable=False
    )
    client = relationship('Client')
    note = Column(String, nullable=True)
    coin = Column(String, nullable=True)

    commission = Column(Numeric, nullable=True)
    execution_id = Column(Integer, ForeignKey('execution.id', ondelete="CASCADE"), nullable=True)
    execution = relationship(
        'Execution',
        foreign_keys=execution_id,
        uselist=False,
        cascade='all, delete',
        lazy='noload'
    )

    #balance = relationship(
    #    'Balance',
    #    back_populates='transfer',
    #    lazy='joined',
    #    uselist=False
    #)

    @hybrid_property
    def type(self) -> TransferType:
        return TransferType.DEPOSIT if self.amount > 0 else TransferType.WITHDRAW

    def __repr__(self):
        return f'{self.type.value} {self.amount}USD ({self.coin})'
