from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from database.dbsync import Base, BaseMixin
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Numeric, Enum, UniqueConstraint, Boolean
from database.dbmodels.mixins.serializer import Serializer
from database.enums import ExecType, Side
from database.dbmodels.symbol import CurrencyMixin


class Execution(Base, Serializer, BaseMixin, CurrencyMixin):
    __tablename__ = 'execution'

    id = Column(Integer, primary_key=True)
    trade_id = Column(ForeignKey('trade.id', ondelete='CASCADE'))
    transfer_id = Column(ForeignKey('transfer.id', ondelete='CASCADE'))

    symbol = Column(String, nullable=False)
    time = Column(DateTime(timezone=True), nullable=False)
    type = Column(Enum(ExecType), nullable=False, default=ExecType.TRADE)

    realized_pnl: Decimal = Column(Numeric, nullable=True)
    price: Decimal = Column(Numeric, nullable=True)
    qty: Decimal = Column(Numeric, nullable=True)
    side = Column(Enum(Side), nullable=True)
    commission: Decimal = Column(Numeric, nullable=True)
    #reduce: bool = Column(Boolean, nullable=False)

    trade = relationship('Trade', lazy='noload', foreign_keys=trade_id)

    __table_args__ = (
        UniqueConstraint(trade_id, transfer_id),
    )

    @hybrid_property
    def net_pnl(self):
        return (self.realized_pnl or Decimal(0)) - (self.commission or Decimal(0))

    @hybrid_property
    def size(self):
        return self.price * self.qty

    @hybrid_property
    def effective_size(self):
        return self.price * self.effective_qty

    @hybrid_property
    def effective_qty(self):
        return self.qty * -1 if self.side == Side.SELL else self.qty

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.side} {self.symbol}@{self.price} {self.qty}'
