from __future__ import annotations
from abc import ABC
from typing import Optional
import sqlalchemy as sa
from pydantic import BaseModel, Extra
from sqlalchemy import orm, TypeDecorator
from datetime import datetime

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from typing_extensions import Self

import tradealpha.common.utils as utils
from tradealpha.common.dbmodels.types import Document, Data
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




class Chapter(Base):
    __tablename__ = 'chapter'

    id = sa.Column(sa.Integer, primary_key=True)
    start_date = sa.Column(sa.Date, nullable=False)
    end_date = sa.Column(sa.Date, nullable=False)

    parent_id = sa.Column(sa.Integer, sa.ForeignKey('chapter.id'), nullable=True)
    children = orm.relationship('Chapter', backref=orm.backref('parent', remote_side=[id]))

    journal_id = sa.Column(sa.Integer,
                           sa.ForeignKey('journal.id', ondelete="CASCADE"),
                           nullable=False)
    #start_balance_id = sa.Column(sa.Integer, sa.ForeignKey('balance.id'), nullable=True)
    #end_balance_id = sa.Column(sa.Integer, sa.ForeignKey('balance.id'), nullable=True)

    balances = orm.relationship('Balance',
                                lazy='noload',
                                secondary=balance_association,
                                order_by='Balance.time')

    journal = orm.relationship('Journal', lazy='noload')
    #start_balance = orm.relationship('Balance', lazy='noload', foreign_keys=start_balance_id)
    #end_balance = orm.relationship('Balance', lazy='noload', foreign_keys=end_balance_id)

    notes = sa.Column(Document, nullable=True)
    data = sa.Column(Data, nullable=True)

    title = sa.Column(sa.String(25), nullable=True)

    @hybrid_property
    def performance(self) -> Gain:
        if self.balances:
            start_balance = self.balances[0]
            end_balance = self.balances[1]
            return Gain(
                relative=utils.calc_percentage(start_balance.total, end_balance.total, string=False),
                absolute=end_balance.realized - start_balance.realized
            )
