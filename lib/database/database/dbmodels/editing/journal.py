from datetime import date, timedelta
from enum import Enum
from operator import and_
from typing import TypedDict, Optional
from typing import TYPE_CHECKING
from fastapi_users_db_sqlalchemy import GUID

import sqlalchemy as sa
from sqlalchemy import orm, select, Column
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship, aliased, mapped_column

from database import dbmodels
from database.dbmodels.editing.template import Template
import core
from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbsync import Base, BaseMixin
from database.dbmodels.types import Document
from database.models.document import DocumentModel

import database.dbmodels.editing.chapter as db_chapter
from dateutil.relativedelta import relativedelta

if TYPE_CHECKING:
    from database.dbmodels.editing.chapter import Chapter

journal_association = sa.Table(
    'journal_association', Base.metadata,
    Column('journal_id', sa.ForeignKey('journal.id', ondelete="CASCADE"), primary_key=True),
    Column('client_id', sa.ForeignKey('client.id', ondelete="CASCADE"), primary_key=True)
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


class Journal(BaseMixin, Base, EditsMixin):
    __tablename__ = 'journal'

    id = mapped_column(sa.Integer, primary_key=True)
    user_id = mapped_column(GUID, sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user = orm.relationship('User', lazy='noload', foreign_keys=user_id)

    title = mapped_column(sa.Text, nullable=False)
    chapter_interval = mapped_column(sa.Enum(IntervalType), nullable=True)
    type = mapped_column(sa.Enum(JournalType), default=JournalType.MANUAL)

    # data: JournalData = mapped_column(Data, nullable=True)

    clients = orm.relationship(
        'Client',
        lazy='noload',
        secondary=journal_association,
        backref=orm.backref('journals', lazy='noload')
    )

    chapters: list['Chapter'] = orm.relationship(
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

    overview = mapped_column(Document, nullable=True)

    default_template_id = mapped_column(sa.ForeignKey('template.id', ondelete="SET NULL"), nullable=True)
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
            new_chapter.doc = template.doc.copy()
            new_chapter.doc[0] = DocumentModel(
                type="title",
                attrs={
                    'level': 1,
                },
                # content=[
                #    DocumentModel(
                #        type="text",
                #        text=core.date_string(date.today())
                #    )
                # ]
            )
            new_chapter.template = template
        else:
            new_chapter.doc = DocumentModel(
                content=[
                    DocumentModel(
                        type="title",
                        attrs={
                            'level': 1,
                        },
                        # content=[
                        #    DocumentModel(
                        #        type="text",
                        #        text=core.date_string(date.today())
                        #    )
                        # ]
                    )
                ],
                type='doc'
            )

        data = {
            'clientIds': [str(id) for id in self.client_ids]
        }

        if new_chapter.data:
            data['dates'] = {
                'since': new_chapter.data.start_date,
                'to': new_chapter.data.end_date,
            }

        new_chapter.doc[0].attrs['data'] = data
        new_chapter.doc[0].type = "title"

        self.chapters.append(new_chapter)
        return new_chapter

    async def update(self, template: Template = None):
        return
        if self.name == JournalType.INTERVAL:
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

    @client_ids.expression
    def client_ids(self):
        return (
            select(dbmodels.Client.id).join(self.clients).scalar_subquery()
        )

    async def init(self, db_session: AsyncSession):
        return

    def flatten_content(self):
        pass
#test = aliased(Client.id)
#
#Journal.client_ids = relationship(
#    test,
#    primaryjoin=and_(
#journal_association.
#    )
#)