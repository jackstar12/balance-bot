from datetime import datetime

import pytz
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property

from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType

from balancebot.api.database import Base


class AmountMixin:
    amount = Column(Float, nullable=False)
    time: DateTime = Column(DateTime(timezone=True), nullable=False)
    extra_currencies = Column(JSONB, nullable=True)
