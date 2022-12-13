from datetime import datetime, timedelta
from operator import and_

from sqlalchemy import Column, Integer, Float, String, Enum, ForeignKey, DateTime, Numeric, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.orm.dynamic import AppenderQuery

from core import safe_cmp
from database.dbasync import safe_op
from database.dbsync import *
from database.enums import TimeFrame
from database.models.market import Market


class Currency(Base):
    __tablename__ = 'currency'

    id = Column(Integer, nullable=False, primary_key=True)
    name: str = Column(String, nullable=False)
    exchange: str = Column(String, nullable=True)


class WithSymbol(Base):
    base_ccy_id = Column(ForeignKey('currency.id', ondelete='CASCADE'), primary_key=True)
    base_ccy = relationship('Currency', foreign_keys=base_ccy_id)

    quote_ccy_id = Column(ForeignKey('currency.id', ondelete='CASCADE'), primary_key=True)
    quote_ccy = relationship('Currency', foreign_keys=quote_ccy_id)

    time = Column(DateTime(timezone=True), nullable=False, primary_key=True)

    @classmethod
    def at_dt(cls,
              dt: datetime,
              tolerance: timedelta,
              market: Market,
              exchange: str = None):
        return (
            select(cls).where(
                cls.time > (dt - tolerance),
                cls.time < (dt - tolerance),
            )
            .join(Currency, and_(
                cls.base_ccy_id == Currency.id,
                Currency.name == market.base,
                safe_op(Currency.exchange, exchange)
            ))
            .join(Currency, and_(
                cls.quote_ccy_id == Currency.id,
                Currency.name == market.quote,
                safe_op(Currency.exchange, exchange)
            ))
        )
    #tf = Column(Enum(TimeFrame), nullable=True)


class OHLC(WithSymbol):
    __tablename__ = 'ohlc'
    open = Column(Numeric, nullable=True)
    high = Column(Numeric, nullable=True)
    low = Column(Numeric, nullable=True)
    close = Column(Numeric, nullable=True)
    tf = Column(Enum(TimeFrame), nullable=True)


