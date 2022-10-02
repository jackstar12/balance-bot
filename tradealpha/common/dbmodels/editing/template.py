from enum import Enum

import sqlalchemy as sa
from sqlalchemy import orm

from tradealpha.common.dbmodels.editing._base import PageMixin
from tradealpha.common.dbmodels.mixins.editsmixin import EditsMixin
from tradealpha.common.dbmodels.types import Data
from tradealpha.common.dbsync import Base


class TemplateType(Enum):
    CHAPTER = "chapter"
    TRADE = "trade"


class Template(Base, EditsMixin, PageMixin):
    __tablename__ = 'template'

    user_id = sa.Column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    data = sa.Column(Data, nullable=True)
    type = sa.Column(sa.Enum(TemplateType), nullable=False)

    user = orm.relationship('User', lazy='noload')
    journals = orm.relationship('Journal',
                                foreign_keys='Journal.default_template_id',
                                back_populates='default_template',
                                lazy='noload')
