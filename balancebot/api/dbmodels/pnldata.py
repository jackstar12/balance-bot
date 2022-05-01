from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType, Table, BigInteger, Numeric, \
    Enum
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base, Meta
from balancebot.api.dbmodels.amountmixin import AmountMixin
from balancebot.api.dbmodels.serializer import Serializer
from balancebot.api.dbmodels.execution import Execution
from enum import Enum as PyEnum


class PNLType(PyEnum):
    UPNL = 0
    RPNL = 1


class PnlData(Base, AmountMixin):
    __tablename__ = 'pnldata'

    id = Column(BigInteger, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id'), nullable=False)

    # type = Column(Enum(PNLType), nullable=False)
