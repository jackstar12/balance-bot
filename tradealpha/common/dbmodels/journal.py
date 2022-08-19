import asyncio
import itertools
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
from tradealpha.common import utils
from tradealpha.common.dbsync import Base
from tradealpha.common.dbmodels.types import Document, DocumentModel, Data
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


class JournalData(TypedDict):
    chapter_interval: Optional[timedelta]


class Journal(Base):
    __tablename__ = 'journal'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(GUID, sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user = orm.relationship('User', lazy='noload', foreign_keys=user_id)

    title = sa.Column(sa.Text, nullable=False)
    chapter_interval = sa.Column(sa.Interval, nullable=True)
    type = sa.Column(sa.Enum(JournalType), default=JournalType.MANUAL)

    #data: JournalData = sa.Column(Data, nullable=True)

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
            parent_id=parent_id
        )

        if self.type == JournalType.INTERVAL:
            start = self.current_chapter.data['end_date'] if self.current_chapter else date.today()
            new_chapter.data['start_date'] = start
            new_chapter.data['end_date'] = new_chapter.data['start_date'] + self.chapter_interval

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

        self.current_chapter = new_chapter
        return new_chapter

    async def update(self, db: AsyncSession, template: Template = None):
        template = template or self.default_template
        if self.type == JournalType.INTERVAL:
            now = utils.utc_now()
            while now > self.current_chapter.data['end_date']:
                chapter = self.create_chapter(template=template)
                db.add(chapter)
        await db.commit()

    @hybrid_property
    def client_ids(self):
        return [client.id for client in self.clients]

    async def init(self, db_session: AsyncSession):
        return

    def flatten_content(self):
        pass