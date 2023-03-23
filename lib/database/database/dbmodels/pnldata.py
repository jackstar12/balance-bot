from decimal import Decimal

from sqlalchemy import Integer, ForeignKey, BigInteger, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from database.dbsync import Base, BaseMixin
from enum import Enum as PyEnum
from database.models.compactpnldata import CompactPnlData
from database.dbmodels.mixins.serializer import Serializer
import database.dbmodels as dbmodels


class PNLType(PyEnum):
    UPNL = 0
    RPNL = 1


class PnlData(Base, Serializer, BaseMixin):
    __tablename__ = 'pnldata'

    id = mapped_column(BigInteger, primary_key=True)
    trade_id = mapped_column(Integer, ForeignKey('trade.id', ondelete="CASCADE"), nullable=False)
    trade = relationship('Trade', lazy='noload', foreign_keys=trade_id)

    realized: Decimal = mapped_column(Numeric, nullable=False)
    unrealized: Decimal = mapped_column(Numeric, nullable=False)

    time = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies = mapped_column(JSONB, nullable=True)

    @property
    def _trade(self):
        return self.sync_session.get(dbmodels.Trade, self.trade_id)

    @hybrid_property
    def total(self) -> Decimal:
        return self.realized + self.unrealized

    @classmethod
    def is_data(cls):
        return True

    def _rate(self, ccy: str):
        return Decimal(self.extra_currencies.get(ccy, 0) if self.extra_currencies and ccy != self.trade.settle else 1)

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

    # type = mapped_column(Enum(PNLType), nullable=False)
