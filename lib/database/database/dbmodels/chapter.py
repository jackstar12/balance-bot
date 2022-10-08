from __future__ import annotations

from datetime import datetime, date, timedelta
from typing import TypedDict, Optional

import sqlalchemy as sa
from sqlalchemy import orm, Date, select, case, func, literal
from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import aliased

import utils
from database.models import BaseModel
from database.dbasync import db_all
from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbmodels.types import Document, Data
from database.models.document import DocumentModel
from database.dbsync import Base
from database.models.gain import Gain

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


class ChapterData(BaseModel):
    start_date: date
    end_date: date

    # def get_end_date(self, interval: timedelta):
    #     return self.start_date + interval


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

    journal = orm.relationship('Journal',
                               lazy='noload')

    # Data
    doc = sa.Column(Document, nullable=True)
    data: Optional[ChapterData] = sa.Column(ChapterData.get_sa_type(validate=True), nullable=True)

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

    @classmethod
    async def all_childs(cls, root_id: int, db):
        included = select(
            Chapter.id,
        ).filter(
            Chapter.parent_id == root_id
        ).cte(name="included", recursive=True)

        included_alias = aliased(included, name="parent")
        chapter_alias = aliased(Chapter, name="child")

        included = included.union_all(
            select(
                chapter_alias.id,
            ).filter(
                chapter_alias.parent_id == included_alias.c.id
            )
        )

        child_stmt = select(
            Chapter
        ).where(
            Chapter.id.in_(included)
        )

        child = await db_all(child_stmt, session=db)
        pass

    @hybrid_property
    def start_date(self):
        return self.data.start_date

    @hybrid_property
    def end_date(self):
        return self.data.end_date

    @hybrid_property
    def all_data(self):
        results = []

        def recursive(current: DocumentModel):
            if current.attrs and current.attrs['data']:
                results.append(current.attrs['data'])

            if current.content:
                for node in current.content:
                    recursive(node)

        recursive(self.doc)

        return results

    @all_data.expression
    def all_data(cls):
        """
        WITH RECURSIVE _tree (key, value) AS (
          SELECT
            NULL   AS key,
            chapter.doc AS value FROM chapter WHERE chapter.id=272
          UNION ALL
          (WITH typed_values AS (SELECT jsonb_typeof(value) as typeof, value FROM _tree)
           SELECT v.*
             FROM typed_values, LATERAL jsonb_each(value) v
             WHERE typeof = 'object' and jsonb_exists(typed_values.value, 'content')
           UNION ALL
           SELECT NULL, element
             FROM typed_values, LATERAL jsonb_array_elements(value) element
             WHERE typeof = 'array'
          )
        )
        SELECT key, value
          FROM _tree


        """

        # https://stackoverflow.com/questions/30132568/collect-recursive-json-keys-in-postgres
        # http://tatiyants.com/how-to-navigate-json-trees-in-postgres-using-recursive-ctes/

        cte = select(
            literal('NULL').label('key'),
            Chapter.doc.label('doc')
        ).cte(recursive=True)
        cte_alias = cte.alias()

        typed_values = select(
            func.jsonb_typeof(cte_alias.c.doc).label('typeof'),
            cte_alias.c.doc.label('value')
        ).cte(name='typed_values')

        each = select(
            func.jsonb_each(typed_values.c.value).label('v')
        ).subquery().lateral()

        array_elemenets = select(
            literal('NULL').label('key'),
            func.jsonb_array_elements(typed_values.c.value).label('element')
        ).subquery().lateral()

        result = typed_values.union_all(
            #select(each.c.v.key, each.c.v.value).where(
            #    typed_values.c.typeof == 'object'
            #),
            select(array_elemenets.c.key, array_elemenets.c.element).select_from(
            ).where(
                typed_values.c.typeof == 'array'
            )
        )

        return select(result).scalar_subquery()
