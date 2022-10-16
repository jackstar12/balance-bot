from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytz
from sqlalchemy import Column, ForeignKey, Numeric, Integer, DateTime, and_, asc, ForeignKeyConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, foreign

from database.dbmodels.mixins.serializer import Serializer
from database.models.gain import Gain

if TYPE_CHECKING:
    from database.dbmodels.balance import Balance as BalanceDB
    from database.models.balance import Amount as AmountModel

from database.dbsync import Base, BaseMixin


class EventScore(Base, Serializer):
    __tablename__ = 'eventscore'

    client_id = Column(ForeignKey('client.id', ondelete='CASCADE'), primary_key=True)
    event_id = Column(ForeignKey('event.id', ondelete='CASCADE'), primary_key=True)
    time = Column(DateTime(timezone=True), primary_key=True, default=lambda: datetime.now(pytz.utc))

    rank = Column(Integer)
    abs_value = Column(Numeric, nullable=True)
    rel_value = Column(Numeric, nullable=True)

    @hybrid_property
    def gain(self):
        if self.rel_value and self.abs_value:
            return Gain.construct(
                relative=self.rel_value,
                absolute=self.abs_value
            )

    @gain.setter
    def gain(self, val: Gain):
        self.rel_value = val.relative
        self.abs_value = val.absolute


class EventEntry(Base, Serializer):
    __tablename__ = 'evententry'

    client_id = Column(ForeignKey('client.id', ondelete='CASCADE'), primary_key=True)
    event_id = Column(ForeignKey('event.id', ondelete='CASCADE'), primary_key=True)
    init_balance_id = Column(ForeignKey('balance.id', ondelete='CASCADE'), nullable=True)
    rekt_on = Column(DateTime(timezone=True), nullable=True)

    init_balance: BalanceDB = relationship('Balance', lazy='noload')
    client = relationship('Client', lazy='noload')
    event = relationship('Event', lazy='noload')

    rank_history: list[EventScore]

    @hybrid_property
    def user_id(self):
        return getattr(self.client, 'user_id')


EventEntry.rank_history = relationship(EventScore,
                                       lazy='noload',
                                       primaryjoin=and_(
                                           EventEntry.client_id == foreign(EventScore.client_id),
                                           EventEntry.event_id == foreign(EventScore.event_id)
                                       ),
                                       order_by=asc(EventScore.time))
