from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy import Column, DateTime, Float


class AmountMixin:
    amount = Column(Float, nullable=False)
    time: DateTime = Column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies = Column(JSONB, nullable=True)
