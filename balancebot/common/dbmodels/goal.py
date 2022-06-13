import operator
from datetime import datetime

import pytz
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship
import enum

from typing_extensions import Self

from balancebot.common.database import Base
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

class Goal(Base, Serializer):
    id: int = Column(Integer, primary_key=True)
    creation_date: datetime = Column(DateTime(timezone=True))
    finish_date: datetime = Column(DateTime(timezone=True))

    expressions: list[Expression]


