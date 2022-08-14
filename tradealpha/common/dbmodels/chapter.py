from __future__ import annotations
from abc import ABC
from typing import Optional

import pytz
import sqlalchemy as sa
from pydantic import BaseModel, Extra
from sqlalchemy import orm, TypeDecorator, select, Date
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property

import tradealpha.common.utils as utils
from tradealpha.common.dbmodels.editsmixin import EditsMixin
from tradealpha.common.dbmodels.types import Document, Data, DocumentModel
from tradealpha.common.dbsync import Base
from tradealpha.common.models.gain import Gain

balance_association = sa.Table(
    'balance_association', Base.metadata,
    sa.Column('balance_id', sa.ForeignKey('balance.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('chapter_id', sa.ForeignKey('chapter.id', ondelete="CASCADE"), primary_key=True)
)

chapter_trade_association = sa.Table(
    'chapter_trade_association', Base.metadata,
    sa.Column('trade_id', sa.ForeignKey('trade.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('chapter_id', sa.ForeignKey('chapter.id', ondelete="CASCADE"), primary_key=True)
)


class Chapter(Base, EditsMixin):
    __tablename__ = 'chapter'

    # Identifiers
    id = sa.Column(sa.Integer, primary_key=True)
    parent_id = sa.Column(sa.ForeignKey('chapter.id', ondelete="CASCADE"),
                          nullable=True)
    journal_id = sa.Column(sa.ForeignKey('journal.id', ondelete="CASCADE"),
                           nullable=False)

    # Relations
    children = orm.relationship('Chapter',
                                backref=orm.backref('parent', remote_side=[id]),
                                lazy='noload',
                                cascade="all, delete")
    balances = orm.relationship('Balance',
                                lazy='noload',
                                secondary=balance_association,
                                order_by='Balance.time')
    journal = orm.relationship('Journal',
                               lazy='noload')

    # Data
    doc: DocumentModel = sa.Column(Document, nullable=True)
    data = sa.Column(Data, nullable=True)

    @hybrid_property
    def title(self):
        self.doc: DocumentModel
        if self.doc:
            titleNode = self.doc.content[0]
            return titleNode.content[0].text if titleNode else None

    @title.expression
    def title(cls):
        return cls.doc['content'][0]['content'][0]['text']

    @hybrid_property
    def start_date(self):
        return self.data.get('start_date') if self.data else None

    @start_date.setter
    def start_date(self, value):
        self.data['start_date'] = value

    @start_date.expression
    def start_date(cls):
        return cls.data['start_date'].as_string().cast(Date)

    @hybrid_property
    def end_date(self):
        return self.data.get('end_date') if self.data else None

    @end_date.expression
    def end_date(cls):
        return cls.data['end_date'].as_string().cast(Date)

    @end_date.setter
    def end_date(self, value):
        self.data['end_date'] = value

    @hybrid_property
    def child_ids(self):
        return [child.id for child in self.children]

    @hybrid_property
    def performance(self) -> Gain:
        if self.balances:
            start_balance = self.balances[0]
            end_balance = self.balances[1]
            return Gain(
                relative=utils.calc_percentage(start_balance.total, end_balance.total, string=False),
                absolute=end_balance.realized - start_balance.realized
            )
