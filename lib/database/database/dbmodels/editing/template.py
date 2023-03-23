from enum import Enum

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.orm import mapped_column

from database.dbmodels.editing.pagemixin import PageMixin
from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbmodels.types import Data
from database.dbsync import Base


class TemplateType(Enum):
    CHAPTER = "chapter"
    TRADE = "trade"


class Template(Base, PageMixin):
    __tablename__ = 'template'

    user_id = mapped_column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    data = mapped_column(Data, nullable=True)
    type = mapped_column(sa.Enum(TemplateType), nullable=False)

    user = orm.relationship('User', lazy='noload')
    journals = orm.relationship('Journal',
                                foreign_keys='Journal.default_template_id',
                                back_populates='default_template',
                                lazy='noload')

    __mapper_args__ = {
        "polymorphic_on": type
    }


class TradeTemplate(Template):
    __mapper_args__ = {
        "polymorphic_identity": TemplateType.TRADE
    }


class ChapterTemplate(Template):
    __mapper_args__ = {
        "polymorphic_identity": TemplateType.CHAPTER
    }
