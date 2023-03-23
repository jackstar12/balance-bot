import operator
from datetime import datetime

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

class Goal(Base, Serializer, BaseMixin):
    id: int = mapped_column(Integer, primary_key=True)
    creation_date: datetime = mapped_column(DateTime(timezone=True))
    finish_date: datetime = mapped_column(DateTime(timezone=True))

    expressions: list[Expression]


