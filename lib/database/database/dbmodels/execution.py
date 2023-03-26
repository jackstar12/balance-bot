from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, mapped_column, Mapped

from database.dbsync import Base, BaseMixin, intpk
from sqlalchemy import Integer, ForeignKey, String, DateTime, Numeric, Enum, UniqueConstraint, Boolean
from database.dbmodels.mixins.serializer import Serializer
from database.enums import ExecType, Side, MarketType
from database.dbmodels.symbol import CurrencyMixin


class Execution(Base, Serializer, BaseMixin, CurrencyMixin):
    __tablename__ = 'execution'

    id: Mapped[intpk]
    trade_id: Mapped[int] = mapped_column(ForeignKey('trade.id', ondelete='CASCADE'))
    transfer_id: Mapped[int] = mapped_column(ForeignKey('transfer.id', ondelete='CASCADE'))

    symbol: Mapped[str]
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    type: Mapped[ExecType] = mapped_column(Enum(ExecType), nullable=False, default=ExecType.TRADE)

    realized_pnl: Mapped[Optional[Decimal]]
    price: Mapped[Optional[Decimal]]
    qty: Mapped[Optional[Decimal]]
    side: Mapped[Side] = mapped_column(Enum(Side), nullable=True)
    commission: Mapped[Optional[Decimal]]

    # If true, the execution will first lower the size of the current trade, otherwise open a new one
    reduce: Mapped[bool] = mapped_column(Boolean, server_default='True')
    market_type: Mapped[MarketType] = mapped_column(Enum(MarketType), nullable=False, server_default='DERIVATIVES')

    trade: Mapped['Trade'] = relationship(lazy='noload', foreign_keys=trade_id)

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
