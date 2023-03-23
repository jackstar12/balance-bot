from __future__ import annotations

from datetime import date
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import orm, select, func, literal
from sqlalchemy.ext.hybrid import hybrid_property

from database.dbmodels.editing.pagemixin import PageMixin
from database.dbmodels.mixins.editsmixin import EditsMixin
from database.dbsync import Base
from database.models import BaseModel
from database.models.document import DocumentModel, TradeData

balance_association = sa.Table(
    'balance_association', Base.metadata,
    mapped_column('balance_id', sa.ForeignKey('balance.id', ondelete="CASCADE"), primary_key=True),
    mapped_column('chapter_id', sa.ForeignKey('chapter.id', ondelete="CASCADE"), primary_key=True)
)

chapter_trade_association = sa.Table(
    'chapter_trade_association', Base.metadata,
    mapped_column('trade_id', sa.ForeignKey('trade.id', ondelete="CASCADE"), primary_key=True),
    mapped_column('chapter_id', sa.ForeignKey('chapter.id', ondelete="CASCADE"), primary_key=True)
)


class ChapterData(BaseModel):
    start_date: date
    end_date: date

    # def get_end_date(self, interval: timedelta):
    #     return self.start_date + interval


class Chapter(Base, PageMixin):
    __tablename__ = 'chapter'

    # Identifiers
    journal_id = mapped_column(sa.ForeignKey('journal.id', ondelete="CASCADE"), nullable=False)
    template_id = mapped_column(sa.ForeignKey('template.id', ondelete="SET NULL"), nullable=True)
    data: Optional[ChapterData] = mapped_column(ChapterData.get_sa_type(validate=True), nullable=True)

    journal = orm.relationship('Journal', lazy='noload')
    template = orm.relationship('Template', lazy='noload')

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
            if current.attrs and 'data' in current.attrs:
                results.append(
                    TradeData(**current.attrs['data'])
                )

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
