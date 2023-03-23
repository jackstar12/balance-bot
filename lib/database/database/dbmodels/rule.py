import operator
from datetime import datetime
import sqlalchemy as sa
import enum

from database.dbsync import Base, BaseMixin
from sqlalchemy import Integer, DateTime
from database.dbmodels.mixins.serializer import Serializer


class OP(enum.Enum):
    greater = operator.ge
    less = operator.le
    equal = operator.eq


value = int | float | bool | str


class Expression:
    var: str
    cmp: value
    op: OP


# Example goal:
# Winrate > 50% && Kelly Optimization = True

class Rule(Base, Serializer, BaseMixin):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creation_date: datetime = mapped_column(DateTime(timezone=True))
    finish_date: datetime = mapped_column(DateTime(timezone=True))
    conditions = mapped_column(sa.JSON, nullable=False)
    expression = mapped_column(sa.JSON, nullable=False)
    expressions: list[Expression]
