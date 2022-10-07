import operator
from datetime import datetime

import enum

from tradealpha.common.dbsync import Base
from sqlalchemy import Column, Integer, DateTime
from tradealpha.common.dbmodels.mixins.serializer import Serializer
from tradealpha.common.enums import IntervalType


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

class Goal(Base, Serializer):
    id: int = Column(Integer, primary_key=True)

    interval = Column(sa.Enum(IntervalType))
    due_date: datetime = Column(DateTime(timezone=True), nullable=True)
    expressions: list[Expression]


