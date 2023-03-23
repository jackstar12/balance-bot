from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

import pytz
from sqlalchemy import ForeignKey, Numeric, Integer, DateTime, and_, asc, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, mapped_column

from database.dbmodels.mixins.serializer import Serializer
from database.models.gain import Gain
from database.dbsync import fkey_name

if TYPE_CHECKING:
    from database.dbmodels.balance import Balance as BalanceDB
    from database.models.balance import Amount as AmountModel

from database.dbsync import Base, BaseMixin


class EventScore(Base, Serializer, BaseMixin):
    __tablename__ = 'eventscore'

    entry_id = mapped_column(ForeignKey('evententry.id', name=fkey_name('eventscore', 'entry_id'), ondelete='CASCADE'), primary_key=True)
    time = mapped_column(DateTime(timezone=True), primary_key=True, default=lambda: datetime.now(pytz.utc))
    rank = mapped_column(Integer)
    abs_value = mapped_column(Numeric, nullable=True)
    rel_value = mapped_column(Numeric, nullable=True)

    entry = relationship('EventEntry')

    async def get_entry(self):
        return await self.async_session.get(EventEntry, self.entry_id)

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


class EventEntry(Base, Serializer, BaseMixin):
    __tablename__ = 'evententry'

    id = mapped_column(Integer, primary_key=True, unique=True)
    user_id = mapped_column(ForeignKey('user.id', name=fkey_name('evententry', 'user_id'), ondelete='CASCADE'),
                     nullable=False)
    client_id = mapped_column(ForeignKey('client.id', name=fkey_name('evententry', 'client_id'), ondelete='SET NULL'),
                       nullable=True)
    event_id = mapped_column(ForeignKey('event.id', name=fkey_name('evententry', 'event_id'), ondelete='CASCADE'),
                      nullable=False)
    init_balance_id = mapped_column(ForeignKey('balance.id', name=fkey_name('evententry', 'init_balance_id'), ondelete='CASCADE'),
                             nullable=True)
    joined_at = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(pytz.utc), nullable=False)

    rekt_on = mapped_column(DateTime(timezone=True), nullable=True)

    init_balance: BalanceDB = relationship('Balance', lazy='noload')
    client = relationship('Client', lazy='noload')
    event = relationship('Event', lazy='noload')
    user = relationship('User', lazy='noload')

    rank_history: list[EventScore]

    __tableargs__ = (
        UniqueConstraint(user_id, event_id, name='evententry_user_id_event_id_key'),
    )

    @hybrid_property
    def exchange(self):
        return getattr(self.client, 'exchange')


EventEntry.rank_history = relationship(EventScore,
                                       lazy='noload',
                                       order_by=asc(EventScore.time))
