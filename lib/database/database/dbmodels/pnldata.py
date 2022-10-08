from decimal import Decimal

from sqlalchemy import Column, Integer, ForeignKey, BigInteger, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from database.dbsync import Base
from enum import Enum as PyEnum
from database.models.compactpnldata import CompactPnlData
from database.dbmodels.mixins.serializer import Serializer


class PNLType(PyEnum):
    UPNL = 0
    RPNL = 1


class PnlData(Base, Serializer):
    __tablename__ = 'pnldata'

    id = Column(BigInteger, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id', ondelete="CASCADE"), nullable=False)
    trade = relationship('Trade', lazy='noload', foreign_keys=trade_id)

    realized: Decimal = Column(Numeric, nullable=False)
    unrealized: Decimal = Column(Numeric, nullable=False)

    time = Column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies = Column(JSONB, nullable=True)

    @hybrid_property
    def total(self) -> Decimal:
        return self.realized + self.unrealized

    @classmethod
    def is_data(cls):
        return True

    def _rate(self, ccy: str):
        return self.extra_currencies.get(ccy, 0) if ccy != self.trade.settle else 1

    def realized_ccy(self, currency: str):
        return self.realized * self._rate(currency)

    def unrealized_ccy(self, currency: str):
        return self.unrealized * self._rate(currency)

    @property
    def compact(self) -> CompactPnlData:
        return CompactPnlData(
            ts=int(self.time.timestamp()),
            realized=self.realized,
            unrealized=self.unrealized
        )

    # type = Column(Enum(PNLType), nullable=False)
