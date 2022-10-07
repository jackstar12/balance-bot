import operator
from datetime import datetime
import sqlalchemy as sa
import enum

from tradealpha.common.dbmodels.mixins.editsmixin import EditsMixin
from tradealpha.common.dbsync import Base
from sqlalchemy import Column, Integer, DateTime
from tradealpha.common.dbmodels.mixins.serializer import Serializer


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

class Rule(Base, Serializer, EditsMixin):
    id: int = Column(Integer, primary_key=True)
    filters = Column(sa.JSON, nullable=False)
    expressions: list[Expression] = Column(sa.JSON, nullable=False)
