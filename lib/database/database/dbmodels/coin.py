from sqlalchemy import Integer, Float, String, Enum, ForeignKey, DateTime
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
from sqlalchemy.orm.dynamic import AppenderQuery

from database.dbsync import *
from database.enums import TimeFrame


class OI(Base):
    __tablename__ = 'oi'

    id = mapped_column(Integer, nullable=False, primary_key=True)
    coin_id = mapped_column(Integer, ForeignKey('coin.id', ondelete='CASCADE'), nullable=False)

    time = mapped_column(DateTime(timezone=True), nullable=False)
    value = mapped_column(Float, nullable=False)
    tf = mapped_column(Enum(TimeFrame), nullable=True)


class Volume(Base):
    __tablename__ = 'volume'

    id = mapped_column(Integer, nullable=False, primary_key=True)
    coin_id = mapped_column(Integer, ForeignKey('coin.id', ondelete='CASCADE'), nullable=False)

    time = mapped_column(DateTime(timezone=True), nullable=False)
    spot_buy = mapped_column(Float, nullable=False)
    spot_sell = mapped_column(Float, nullable=False)
    perp_buy = mapped_column(Float, nullable=False)
    perp_sell = mapped_column(Float, nullable=False)
    tf = mapped_column(Enum(TimeFrame), nullable=True)


class Coin(Base):
    __tablename__ = 'coin'

    id = mapped_column(Integer, nullable=False, primary_key=True)
    name: str = mapped_column(String, nullable=False)
    exchange: str = mapped_column(String, nullable=True)

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

