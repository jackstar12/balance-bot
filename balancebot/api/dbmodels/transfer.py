import enum
import sqlalchemy as sa
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType, Table, BigInteger, Numeric
from sqlalchemy.orm import relationship, backref
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base, Meta
from balancebot.api.dbmodels.serializer import Serializer
from balancebot.api.dbmodels.execution import Execution


class Type(enum.Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"


class Transfer(Base):
    __tablename__ = 'transfer'

    id = Column(BigInteger, primary_key=True)
    client_id = Column(
        Integer,
        ForeignKey('client.id', ondelete="CASCADE"),
        nullable=False
    )
    amount = Column(Numeric, nullable=False)
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
