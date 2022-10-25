import enum
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Optional

from sqlalchemy import Column, Integer, ForeignKey, String, BigInteger, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from database.dbsync import Base
from database.enums import Side


class TransferType(enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


class RawTransfer(NamedTuple):
    amount: Decimal
    time: datetime
    coin: str
    fee: Optional[Decimal]


class Transfer(Base):
    __tablename__ = 'transfer'

    id = Column(BigInteger, primary_key=True)
    client_id = Column(
        Integer,
        ForeignKey('client.id', ondelete="CASCADE"),
        nullable=False
    )
    execution_id = Column(Integer, ForeignKey('execution.id', ondelete="CASCADE"), nullable=False)

    note = Column(String, nullable=True)
    coin = Column(String, nullable=True)

    client = relationship('Client')
    execution = relationship(
        'Execution',
        foreign_keys=execution_id,
        uselist=False,
        cascade='all, delete',
        lazy='joined'
    )

    @hybrid_property
    def time(self):
        return self.execution.time

    @hybrid_property
    def commission(self):
        return self.execution.commission

    @hybrid_property
    def size(self):
        return self.execution.size

    #balance = relationship(
    #    'Balance',
    #    back_populates='transfer',
    #    lazy='joined',
    #    uselist=False
    #)

    @hybrid_property
    def type(self) -> TransferType:
        return TransferType.DEPOSIT if self.execution.side == Side.BUY else TransferType.WITHDRAW

    def __repr__(self):
        return f'{self.type.value} {self.amount}USD ({self.coin})'
