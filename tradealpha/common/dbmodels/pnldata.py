from decimal import Decimal

from sqlalchemy import Column, Integer, ForeignKey, BigInteger, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from tradealpha.common.dbsync import Base
from tradealpha.common.dbmodels.amountmixin import AmountMixin
from enum import Enum as PyEnum

from tradealpha.common.dbmodels.serializer import Serializer


class PNLType(PyEnum):
    UPNL = 0
    RPNL = 1


class PnlData(Base, Serializer):
    __tablename__ = 'pnldata'

    id = Column(BigInteger, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id', ondelete="CASCADE"), nullable=False)
    trade = relationship('Trade', foreign_keys=trade_id)

    realized = Column(Numeric, nullable=False)
    unrealized = Column(Numeric, nullable=False)

    time = Column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies = Column(JSONB, nullable=True)

    @hybrid_property
    def total(self) -> Decimal:
        return round(self.realized + self.unrealized, ndigits=3)

    @hybrid_property
    def amount(self) -> Decimal:
        return round(self.realized + self.unrealized, ndigits=3)

    @classmethod
    def is_data(cls):
        return True



    # type = Column(Enum(PNLType), nullable=False)
