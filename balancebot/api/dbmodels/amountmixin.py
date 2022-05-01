from datetime import datetime

import pytz
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.api.database import Base
from sqlalchemy import Column, Integer, ForeignKey, String, DateTime, Float, PickleType

import balancebot.bot.config as config
from balancebot.api.dbmodels.serializer import Serializer


class AmountMixin:
    amount = Column(Float, nullable=False)
    time: DateTime = Column(DateTime(timezone=True), nullable=False)
    extra_currencies = Column(JSONB, nullable=True)
