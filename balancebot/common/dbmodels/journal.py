import asyncio
import itertools
from itertools import zip_longest

import sqlalchemy as sa
from fastapi_users_db_sqlalchemy import GUID
from sqlalchemy import orm, Table
from datetime import datetime, timedelta, date

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.common import utils
from balancebot.common.database import Base
from balancebot.common.dbmodels.chapter import Chapter
from balancebot.common.models.daily import Interval
from balancebot.common.models.gain import Gain
from balancebot.common.utils import list_last

journal_association = sa.Table(
    'journal_association', Base.metadata,
    sa.Column('journal_id', sa.ForeignKey('journal.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('client_id', sa.ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
)


class Journal(Base):
    __tablename__ = 'journal'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(GUID, sa.ForeignKey('user.id'), nullable=False)
    user = orm.relationship('User', lazy='noload', foreign_keys=user_id)

    title = sa.Column(sa.Text, nullable=False)
    chapter_interval = sa.Column(sa.Interval, nullable=False)

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

    async def init(self, db_session: AsyncSession):
        client_intervals = await asyncio.gather(*[
            utils.calc_intervals(
                client,
                self.chapter_interval,
                as_string=False,
                db_session=db_session
            )
            for client in self.clients
        ])

        current_chapter = None
        today = date.today()
        chapters = []
        for interval in sorted(
                itertools.chain.from_iterable(client_intervals),
                key=lambda inter: inter.day
        ):
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

        db_session.add_all([
            Chapter(
                start_date=interval.day,
                end_date=interval.day + self.chapter_interval,
                client=self,
                journal=self,
                start_balance=interval.start_balance,
                end_balance=interval.end_balance,
            )
            for interval in intervals
        ])
        db_session.add(new_journal)
        await db_session.commit()
