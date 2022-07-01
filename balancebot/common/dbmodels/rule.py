import operator
from datetime import datetime
import sqlalchemy as sa
import pytz
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
import enum

from typing_extensions import Self

from balancebot.common.dbsync import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Numeric, Enum
from balancebot.common.dbmodels.serializer import Serializer
from balancebot.common.enums import ExecType, Side


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

class Rule(Base, Serializer):
    id: int = Column(Integer, primary_key=True)
    creation_date: datetime = Column(DateTime(timezone=True))
    finish_date: datetime = Column(DateTime(timezone=True))
    conditions = Column(sa.JSON, nullable=False)
    expression = Column(sa.JSON, nullable=False)
    expressions: list[Expression]
