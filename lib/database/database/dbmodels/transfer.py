import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Optional

from sqlalchemy import Integer, ForeignKey, String, BigInteger, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from database.dbsync import Base
from database.enums import Side, MarketType
from database.models import BaseModel


class TransferType(enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


class RawTransfer(BaseModel):
    amount: Decimal
    time: datetime
    coin: str
    fee: Optional[Decimal]
    market_type: Optional[MarketType]


class Transfer(Base):
    __tablename__ = 'transfer'

    id = mapped_column(Integer, primary_key=True)
    client_id = mapped_column(
        Integer,
        ForeignKey('client.id', ondelete="CASCADE"),
        nullable=False
    )
    execution_id = mapped_column(Integer, ForeignKey('execution.id', ondelete="CASCADE"), nullable=False)

    note = mapped_column(String, nullable=True)
    coin = mapped_column(String, nullable=True)

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
        return self.execution.effective_size

    @hybrid_property
    def amount(self):
        return self.execution.qty


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
