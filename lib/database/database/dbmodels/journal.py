from datetime import date, datetime, timedelta
from enum import Enum
from typing import Iterator, TypedDict, Optional
from typing import TYPE_CHECKING
from fastapi_users_db_sqlalchemy import GUID

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property

from .template import Template
from .. import utils
from database.dbsync import Base, BaseMixin
from database.dbmodels.types import Document
from database.models.document import DocumentModel

import database.dbmodels.chapter as db_chapter
from dateutil.relativedelta import relativedelta
if TYPE_CHECKING:
    from database.dbmodels.chapter import Chapter

journal_association = sa.Table(
    'journal_association', Base.metadata,
    sa.Column('journal_id', sa.ForeignKey('journal.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('client_id', sa.ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
)


class JournalType(Enum):
    MANUAL = "manual"
    INTERVAL = "interval"


class JournalData(TypedDict):
    chapter_interval: Optional[timedelta]

class IntervalType(Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


class Journal(Base, BaseMixin):
    __tablename__ = 'journal'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(GUID, sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user = orm.relationship('User', lazy='noload', foreign_keys=user_id)

    title = sa.Column(sa.Text, nullable=False)
    chapter_interval = sa.Column(sa.Enum(IntervalType), nullable=True)
    type = sa.Column(sa.Enum(JournalType), default=JournalType.MANUAL)

    #data: JournalData = sa.Column(Data, nullable=True)

    clients = orm.relationship(
        'Client',
        lazy='noload',
        secondary=journal_association,
        backref=orm.backref('journals', lazy='noload')
    )

    chapters: 'list[Chapter]' = orm.relationship(
        'Chapter',
        lazy='noload',
        cascade="all, delete",
        back_populates="journal"
    )

    current_chapter: 'Chapter' = orm.relationship('Chapter',
                                                  primaryjoin="and_("
                                                              "Chapter.journal_id == Journal.id, "
                                                              "Chapter.data['end_date'].astext.cast(Date) >= func.current_date()"
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
            parent_id=parent_id,
            data=None
        )

        if self.type == JournalType.INTERVAL:
            if self.current_chapter:
                start = self.current_chapter.data.end_date + timedelta(days=1)
            else:
                today = date.today()
                if self.chapter_interval == IntervalType.MONTH:
                    start = date(year=today.year, month=today.month, day=1)
                elif self.chapter_interval == IntervalType.WEEK:
                    start = today - timedelta(days=today.weekday())
                else:
                    start = today

            if self.chapter_interval == IntervalType.WEEK:
                end_date = start + timedelta(days=6)
            elif self.chapter_interval == IntervalType.MONTH:
                end_date = start + relativedelta(months=+1, days=-1)
            else:
                end_date = start

            new_chapter.data = db_chapter.ChapterData(
                start_date=start,
                end_date=end_date
            )

        if template:
            new_chapter.doc = template.doc
            new_chapter.doc.content = template.doc.content[0:]

            new_chapter.doc[0] = DocumentModel(
                type="title",
                attrs={
                    'level': 1,
                    'data': {
                        'dates': {
                            'since': new_chapter.data.start_date,
                            'to': new_chapter.data.end_date,
                        },
                        'clientIds': [str(id) for id in self.client_ids]
                    }
                },
                content=[
                    DocumentModel(
                        type="text",
                        text=utils.date_string(date.today())
                    )
                ]
            )
        self.chapters.append(new_chapter)
        return new_chapter

    async def update(self, db: AsyncSession, template: Template = None):
        if self.type == JournalType.INTERVAL:
            template = template or self.default_template
            today = date.today()
            while not self.latest_chapter or today > self.latest_chapter.data.end_date:
                chapter = self.create_chapter(template=template)
                db.add(chapter)
        await db.commit()

    @hybrid_property
    def latest_chapter(self):
        return self.chapters[-1] if self.chapters else None

    @hybrid_property
    def client_ids(self):
        return [client.id for client in self.clients]

    async def init(self, db_session: AsyncSession):
        return

    def flatten_content(self):
        pass