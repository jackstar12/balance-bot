from datetime import datetime
from decimal import Decimal

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from database.dbsync import Base, BaseMixin
from sqlalchemy import Integer, ForeignKey, String, DateTime, Numeric, Enum, UniqueConstraint, Boolean
from database.dbmodels.mixins.serializer import Serializer
from database.enums import ExecType, Side, MarketType
from database.dbmodels.symbol import CurrencyMixin


class Execution(Base, Serializer, BaseMixin, CurrencyMixin):
    __tablename__ = 'execution'

    id = mapped_column(Integer, primary_key=True)
    trade_id = mapped_column(ForeignKey('trade.id', ondelete='CASCADE'))
    transfer_id = mapped_column(ForeignKey('transfer.id', ondelete='CASCADE'))

    symbol = mapped_column(String, nullable=False)
    time = mapped_column(DateTime(timezone=True), nullable=False)
    type = mapped_column(Enum(ExecType), nullable=False, default=ExecType.TRADE)

    realized_pnl: Decimal = mapped_column(Numeric, nullable=True)
    price: Decimal = mapped_column(Numeric, nullable=True)
    qty: Decimal = mapped_column(Numeric, nullable=True)
    side = mapped_column(Enum(Side), nullable=True)
    commission: Decimal = mapped_column(Numeric, nullable=True)

    # If true, the execution will first lower the size of the current trade, otherwise open a new one
    reduce: bool = mapped_column(Boolean, server_default='True')
    market_type = mapped_column(Enum(MarketType), nullable=False, server_default='DERIVATIVES')

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
