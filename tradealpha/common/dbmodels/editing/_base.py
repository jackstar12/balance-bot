from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import orm, select
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased, declared_attr

from tradealpha.common.dbasync import db_all
from tradealpha.common.dbmodels.types import Document
from tradealpha.common.models.document import DocumentModel


class PageMixin:
    # Identifiers
    id = sa.Column(sa.Integer, primary_key=True)

    @declared_attr
    def parent_id(self):
        return sa.Column(sa.ForeignKey(self.id, ondelete="CASCADE"),
                         nullable=True)

    if TYPE_CHECKING:
        doc: DocumentModel
    else:
        doc = sa.Column(Document, nullable=True)

    @declared_attr
    def children(self):
        return orm.relationship(self,
                                backref=orm.backref('parent', remote_side=[self.id]),
                                lazy='noload',
                                cascade="all, delete")

    @hybrid_property
    def title(self):
        self.doc: DocumentModel
        if self.doc:
            titleNode = self.doc.content[0]
            return titleNode.content[0].text if titleNode else None

    @hybrid_property
    def body(self):
        self.doc: DocumentModel
        if self.doc:
            return self.doc.content[0:]

    @title.expression
    def title(cls):
        return cls.doc['content'][0]['content'][0]['text']

    @hybrid_property
    def child_ids(self):
        return [child.id for child in self.children]

    @classmethod
    async def all_childs(cls, root_id: int, db):
        included = select(
            cls.id,
        ).filter(
            cls.parent_id == root_id
        ).cte(name="included", recursive=True)

        included_alias = aliased(included, name="parent")
        chapter_alias = aliased(cls, name="child")

        included = included.union_all(
            select(
                chapter_alias.id,
            ).filter(
                chapter_alias.parent_id == included_alias.c.id
            )
        )

        child_stmt = select(
            cls
        ).where(
            cls.id.in_(included)
        )

        child = await db_all(child_stmt, session=db)
        pass
