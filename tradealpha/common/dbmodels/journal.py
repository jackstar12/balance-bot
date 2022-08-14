import asyncio
import itertools
from datetime import date
from enum import Enum
from typing import Iterator
from typing import TYPE_CHECKING
from fastapi_users_db_sqlalchemy import GUID

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property

from .template import Template
from .. import utils
from ..dbsync import Base
from ..utils import list_last
from ..dbmodels.types import Document, DocumentModel
import tradealpha.common.dbmodels.chapter as db_chapter

if TYPE_CHECKING:
    from tradealpha.common.dbmodels.chapter import Chapter

journal_association = sa.Table(
    'journal_association', Base.metadata,
    sa.Column('journal_id', sa.ForeignKey('journal.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('client_id', sa.ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
)


class JournalType(Enum):
    MANUAL = "manual"
    INTERVAL = "interval"


class Journal(Base):
    __tablename__ = 'journal'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(GUID, sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user = orm.relationship('User', lazy='noload', foreign_keys=user_id)

    title = sa.Column(sa.Text, nullable=False)
    chapter_interval = sa.Column(sa.Interval, nullable=True)
    type = sa.Column(sa.Enum(JournalType), default=JournalType.MANUAL)

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

    current_chapter: 'Chapter' = orm.relationship('Chapter',
                                                  primaryjoin="and_("
                                                              "Chapter.journal_id == Journal.id, "
                                                              "Chapter.end_date >= func.current_date()"
                                                              ")",
                                                  lazy='noload',
                                                  back_populates="journal",
                                                  viewonly=True,
                                                  uselist=False
                                                  )

    overview = sa.Column(Document, nullable=True)

    default_template_id = sa.Column(sa.ForeignKey('template.id', ondelete="SET NULL"), nullable=True)
    default_template = orm.relationship('Template',
                                        lazy='noload',
                                        foreign_keys=default_template_id,
                                        uselist=False)

    def create_chapter(self, parent_id: int = None, template: Template = None):
        new_chapter = db_chapter.Chapter(
            journal=self,
            parent_id=parent_id
        )

        if template:
            new_chapter.doc = template.doc
            new_chapter.doc.content = template.doc.content[1:]
            new_chapter.data = template.data

            template_title_node = new_chapter.doc[0]
            if template_title_node.type == 'templateTitle':
                if template_title_node.attrs['type'] == 'constant':
                    new_chapter.doc[0] = DocumentModel(
                        type="title",
                        attrs={'level': 1},
                        content=[
                            DocumentModel(
                                type="text",
                                text=template_title_node.attrs['content']
                            )
                        ]
                    )
                if template_title_node.attrs['type'] == 'date':
                    new_chapter.doc[0] = DocumentModel(
                        type="title",
                        attrs={'level': 1},
                        content=[
                            DocumentModel(
                                type="text",
                                text=utils.date_string(date.today())
                            )
                        ]
                    )

        return new_chapter

    @hybrid_property
    def client_ids(self):
        return [client.id for client in self.clients]

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
                chapters.append(
                    db_chapter.Chapter(
                        data=dict(
                            start_balance_id=interval.start_balance.id
                        ),
                        start_date=interval.day,
                        end_date=interval.day + self.chapter_interval,
                        journal=self,
                    )
                )
            else:
                current_chapter.balances.append(interval.start_balance)
                current_chapter.balances.append(interval.end_balance)

        self.current_chapter = current_chapter

        db_session.add_all(chapters)
        return

    async def re_init(self, db_session: AsyncSession):
        interval_iter = iter(await self._calc_intervals(db_session))
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
