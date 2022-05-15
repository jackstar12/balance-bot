from sqlalchemy.dialects.postgresql import JSONB

from sqlalchemy import Column, DateTime, Numeric
from sqlalchemy import orm


class AmountMixin:
    amount = Column(Numeric, nullable=False)
    time: DateTime = Column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies = Column(JSONB, nullable=True)

    #@orm.reconstructor
    #def init_on_load(self):
    #    self.error = None

    #def __init__(self, error=None, *args, **kwargs):
    #    super().__init__(*args, **kwargs)
    #    self.error = error
