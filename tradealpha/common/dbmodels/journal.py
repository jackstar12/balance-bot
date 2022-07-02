import asyncio
import itertools
from enum import Enum
from itertools import zip_longest
from typing import Iterator

import sqlalchemy as sa
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import orm, Table
from datetime import datetime, timedelta, date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property

from tradealpha.common import utils
from tradealpha.common.dbsync import Base
from tradealpha.common.dbmodels.chapter import Chapter
from tradealpha.common.models.daily import Interval
from tradealpha.common.models.gain import Gain
from tradealpha.common.utils import list_last

journal_association = sa.Table(
    'journal_association', Base.metadata,
    sa.Column('journal_id', sa.ForeignKey('journal.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('client_id', sa.ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
)


class JournalType(Enum):
    MANUAL = 1
    CLIENTS = 2


class Journal(Base):
    __tablename__ = 'journal'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(GUID, sa.ForeignKey('user.id'), nullable=False)
    user = orm.relationship('User', lazy='noload', foreign_keys=user_id)

    title = sa.Column(sa.Text, nullable=False)
    chapter_interval = sa.Column(sa.Interval, nullable=False)
    auto_generate = sa.Column(sa.Boolean, default=True)
    track_performance = sa.Column(sa.Boolean, default=True)
    type = sa.Column(sa.Enum(JournalType), default=JournalType.CLIENTS)

    clients = orm.relationship(
        'Client',
        lazy='noload',
        secondary=journal_association,
        backref=orm.backref('journals', lazy='noload')
    )

    chapters = orm.relationship(
        'Chapter',
        lazy='noload',
        cascade="all, delete",
        back_populates="journal"
    )

    current_chapter: Chapter = orm.relationship('Chapter',
                                                primaryjoin="and_("
                                                            "Chapter.journal_id == Journal.id, "
                                                            "Chapter.end_date >= func.current_date()"
                                                            ")",
                                                lazy='noload',
                                                back_populates="journal",
                                                viewonly=True,
                                                uselist=False
                                                )

    async def _calc_intervals(self, db_session: AsyncSession) -> Iterator:
        client_intervals = await asyncio.gather(*[
            utils.calc_intervals(
                client,
                self.chapter_interval,
                as_string=False,
                db_session=db_session
            )
            for client in self.clients
        ])
        return sorted(
            itertools.chain.from_iterable(client_intervals),
            key=lambda inter: inter.day
        )

    async def init(self, db_session: AsyncSession):
        client_intervals = await self._calc_intervals(db_session)

        current_chapter = None
        chapters = []
        for interval in client_intervals:
            current_chapter = list_last(chapters, None)
            if not current_chapter or interval.day >= current_chapter.end_date:
                chapters.append(Chapter(
                    start_date=interval.day,
                    end_date=interval.day + self.chapter_interval,
                    journal=self,
                    balances=[interval.start_balance, interval.end_balance],
                ))
            else:
                current_chapter.balances.append(interval.start_balance)
                current_chapter.balances.append(interval.end_balance)

        self.current_chapter = current_chapter

        db_session.add(self)
        db_session.add_all(chapters)
        await db_session.commit()
        return

    async def re_init(self, db_session: AsyncSession):
        interval_iter = await self._calc_intervals(db_session)
        cur_interval = next(interval_iter, None)

        for index, chapter in enumerate(self.chapters):
            chapter.balances = []

            while cur_interval and cur_interval.day <= chapter.start_day:
                if cur_interval.day == chapter.start_day:
                    chapter.balances.append(cur_interval.start_balance)
                    chapter.balances.append(cur_interval.end_balance)
                else:
                    self.chapters.insert(index, Chapter(
                        start_date=cur_interval.day,
                        end_date=cur_interval.day + self.chapter_interval,
                        journal=self,
                        balances=[],
                    ))

                cur_interval = next(interval_iter, None)

        await db_session.commit()
