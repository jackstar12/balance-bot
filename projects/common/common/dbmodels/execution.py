from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Numeric, Enum
from common.dbmodels.mixins.serializer import Serializer
from common.enums import ExecType, Side
from common.dbmodels.symbol import CurrencyMixin


class Execution(Base, Serializer, CurrencyMixin):
    __tablename__ = 'execution'
    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id', ondelete='CASCADE'), nullable=True)
    trade = relationship('Trade', lazy='noload', foreign_keys=trade_id)

    symbol = Column(String, nullable=False)
    time: datetime = Column(DateTime(timezone=True), nullable=False)
    type = Column(Enum(ExecType), nullable=False, default=ExecType.TRADE)

    realized_pnl: Decimal = Column(Numeric, nullable=True)
    price: Decimal = Column(Numeric, nullable=True)
    qty: Decimal = Column(Numeric, nullable=True)
    side = Column(Enum(Side), nullable=True)
    commission: Decimal = Column(Numeric, nullable=True)

    @hybrid_property
    def effective_qty(self):
        return self.qty * self.side.value if self.side else 0

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.side} {self.symbol}@{self.price} {self.qty}'
