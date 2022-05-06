from sqlalchemy import Column, Integer, ForeignKey, BigInteger

from balancebot.common.database import Base
from balancebot.common.dbmodels.amountmixin import AmountMixin
from enum import Enum as PyEnum


class PNLType(PyEnum):
    UPNL = 0
    RPNL = 1


class PnlData(Base, AmountMixin):
    __tablename__ = 'pnldata'

    id = Column(BigInteger, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id'), nullable=False)

    # type = Column(Enum(PNLType), nullable=False)
