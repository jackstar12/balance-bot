import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.ext.hybrid import hybrid_property

from common.dbmodels.mixins.editsmixin import EditsMixin
from common.dbmodels.types import Document, Data
from common.models.document import DocumentModel

from common.dbsync import Base
from typing import TYPE_CHECKING


class Template(Base, EditsMixin):
    __tablename__ = 'template'

    id = sa.Column(sa.Integer, primary_key=True)
    user_id = sa.Column(sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    user = orm.relationship('User', lazy='noload')

    if TYPE_CHECKING:
        doc: DocumentModel
    else:
        doc = sa.Column(Document, nullable=True)
    data = sa.Column(Data, nullable=True)

    journals = orm.relationship('Journal',
                                foreign_keys='Journal.default_template_id',
                                back_populates='default_template',
                                lazy='noload')

    @hybrid_property
    def title(self):
        return self.doc.title if self.doc else None

    @title.expression
    def title(self):
        return self.doc.content[0].content[0].text

