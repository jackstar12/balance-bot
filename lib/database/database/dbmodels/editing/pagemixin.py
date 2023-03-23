from __future__ import annotations

import operator
from typing import TYPE_CHECKING

import sqlalchemy
import sqlalchemy as sa
from sqlalchemy import orm, select, func, text, or_, Date, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased, declared_attr

from core import safe_cmp, map_list
from database.dbasync import db_all, safe_op
from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbmodels.types import Document
from database.models.document import DocumentModel

if TYPE_CHECKING:
    from database.dbmodels.client import ClientQueryParams


def cmp_dates(col, val):
    return or_(
        col.astext.cast(Date) <= val.date() if val else True,
        col == JSONB.NULL
    )


class PageMixin(EditsMixin):
    # Identifiers
    id = mapped_column(sa.Integer, primary_key=True)

    @declared_attr
    def parent_id(self):
        return mapped_column(sa.ForeignKey(self.id, ondelete="CASCADE"),
                         nullable=True)

    if TYPE_CHECKING:
        doc: DocumentModel
    else:
        doc = mapped_column(Document, nullable=True)

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

    @title.expression
    def title(self):
        return self.doc['content'][0]['content'][0]['text'].astext

    @hybrid_property
    def body(self):
        self.doc: DocumentModel
        if self.doc:
            return self.doc.content[1:]

    @hybrid_property
    def child_ids(self):
        return [child.id for child in self.children]

    @child_ids.expression
    def child_ids(self):
        other = aliased(self)
        return select(other.id).where(self.id == other.parent_id)

    @classmethod
    def query_nodes(cls, root_id: id, query_params: ClientQueryParams = None, trade_ids: list[int] = None):
        tree = select(
            func.jsonb_array_elements(cls.doc['content']).cast(JSONB).label('node')
        ).where(
            cls.id == root_id
        ).cte(name="nodes", recursive=True)

        attrs = tree.c.node['attrs']

        tree = tree.union(
            select(
                func.jsonb_array_elements(tree.c.node['content']).cast(JSONB)
            ).where(
                func.jsonb_exists(attrs, 'data')
            )
        )
        data = tree.c.node['attrs']['data']

        whereas = (
            data != JSONB.NULL,
            cmp_dates(data['dates']['to'], query_params.to),
            cmp_dates(data['dates']['since'], query_params.since),
            or_(
                data['clientIds'] == JSONB.NULL,
                data['clientIds'].contains(map_list(str, query_params.client_ids))
            ),
            #or_(
            #    data['tradeIds'] == JSONB.NULL,
            #    data['tradeIds'].contains(trade_ids and map_list(str, trade_ids))
            #)
        )

        return select(data).where(*whereas)

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
