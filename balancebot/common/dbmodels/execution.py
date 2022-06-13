from datetime import datetime

import pytz
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from balancebot.common.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Numeric, Enum
from balancebot.common.dbmodels.serializer import Serializer
from balancebot.common.enums import ExecType, Side


class Execution(Base, Serializer):
    __tablename__ = 'execution'
    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id', ondelete='CASCADE'), nullable=True)
    trade = relationship('Trade', lazy='noload', foreign_keys=trade_id)

    symbol = Column(String, nullable=False)
    price = Column(Numeric, nullable=False)
    qty = Column(Numeric, nullable=False)
    side = Column(Enum(Side), nullable=False)
    time: datetime = Column(DateTime(timezone=True), nullable=False)
    type = Column(Enum(ExecType), nullable=True)

    commission = Column(Numeric, nullable=True)
    realized_pnl = Column(Numeric, nullable=True)

    @hybrid_property
    def effective_qty(self):
        return self.qty * self.side.value

