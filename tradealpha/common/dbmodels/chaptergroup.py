

import sqlalchemy as sa
from sqlalchemy import orm

from tradealpha.common.dbsync import Base





class ChapterGroup(Base):
    __tablename__ = 'chaptergroup'

    id = sa.Column(sa.Integer, primary_key=True)
    journal_id = sa.Column(sa.Integer, sa.ForeignKey('journal.id'), nullable=False)
    journal = orm.relationship('Journal', lazy='noload', foreign_keys=journal_id)
    title = sa.Column(sa.Text, nullable=False)
    content = sa.Column(sa.JSON, nullable=False)
