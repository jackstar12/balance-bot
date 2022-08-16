import sqlalchemy as sa
from sqlalchemy import orm

from tradealpha.common.dbmodels.mixins.editsmixin import EditsMixin
from tradealpha.common.dbmodels.types import Document, Data, DocumentModel

from tradealpha.common.dbsync import Base
from typing import TYPE_CHECKING

class Template(Base, EditsMixin):
    __tablename__ = 'template'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user = orm.relationship('User', lazy='noload')
    title = sa.Column(sa.Text, nullable=False)

    if TYPE_CHECKING:
        doc: DocumentModel
    else:
        doc = sa.Column(Document, nullable=True)
    data = sa.Column(Data, nullable=True)

    journals = orm.relationship('Journal',
                                foreign_keys='Journal.default_template_id',
                                back_populates='default_template',
                                lazy='noload')

