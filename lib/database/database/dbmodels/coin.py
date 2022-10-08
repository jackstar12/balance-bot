from sqlalchemy import Column, Integer, Float, String, Enum, ForeignKey, DateTime
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.orm.dynamic import AppenderQuery

from database.dbsync import *
from database.enums import TimeFrame


class OI(Base):
    __tablename__ = 'oi'

    id = Column(Integer, nullable=False, primary_key=True)
    coin_id = Column(Integer, ForeignKey('coin.id', ondelete='CASCADE'), nullable=False)

    time = Column(DateTime(timezone=True), nullable=False)
    value = Column(Float, nullable=False)
    tf = Column(Enum(TimeFrame), nullable=True)


class Volume(Base):
    __tablename__ = 'volume'

    id = Column(Integer, nullable=False, primary_key=True)
    coin_id = Column(Integer, ForeignKey('coin.id', ondelete='CASCADE'), nullable=False)

    time = Column(DateTime(timezone=True), nullable=False)
    spot_buy = Column(Float, nullable=False)
    spot_sell = Column(Float, nullable=False)
    perp_buy = Column(Float, nullable=False)
    perp_sell = Column(Float, nullable=False)
    tf = Column(Enum(TimeFrame), nullable=True)


class Coin(Base):
    __tablename__ = 'coin'

    id = Column(Integer, nullable=False, primary_key=True)
    name: str = Column(String, nullable=False)
    exchange: str = Column(String, nullable=True)

    volume_history: AppenderQuery = relationship(
        'Volume', lazy='dynamic', cascade='all, delete', backref='coin',
    )
    oi_history: AppenderQuery = relationship(
        'OI', lazy='dynamic', cascade='all, delete', backref='coin',
    )

    @hybrid_property
    def perp_ticker(self):
        return f'{self.name}-PERP'

    @hybrid_property
    def spot_ticker(self):
        return f'{self.name}/USD'

    def __hash__(self):
        return self.id.__hash__()

