from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float
from balancebot.api.dbmodels.serializer import Serializer


class Execution(Base, Serializer):
    __tablename__ = 'execution'
    id = Column(Integer, primary_key=True)
    trade_id = Column(Integer, ForeignKey('trade.id', ondelete='CASCADE'), nullable=True)

    symbol = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    qty = Column(Float, nullable=False)
    side = Column(String, nullable=False)
    time = Column(DateTime, nullable=False)
    type = Column(String, nullable=True)
