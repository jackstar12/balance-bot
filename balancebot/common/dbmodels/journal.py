import sqlalchemy as sa
from sqlalchemy import orm
from datetime import datetime

from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.common import utils
from balancebot.common.database import Base
from balancebot.common.models.clientgain import Gain


class Journal(Base):
    __tablename__ = 'journal'

    id = sa.Column(sa.Integer, primary_key=True)
    client_id = sa.Column(sa.Integer, sa.ForeignKey('client.id'), nullable=False)
    client = orm.relationship('Client', lazy='noload')

    title = sa.Column(sa.Text, nullable=False)
    chapter_interval = sa.Column(sa.Interval, nullable=False)

    chapters = orm.relationship(
        'Chapter',
        lazy='noload',
        cascade="all, delete",
        back_populates="journal"
    )

    current_chapter = orm.relationship('Chapter',
                                       primaryjoin="and_("
                                                   "Chapter.journal_id == Journal.id, "
                                                   "Chapter.end_date >= func.current_date()"
                                                   ")",
                                       lazy='noload',
                                       back_populates="journal",
                                       viewonly=True,
                                       uselist=False
                                       )
