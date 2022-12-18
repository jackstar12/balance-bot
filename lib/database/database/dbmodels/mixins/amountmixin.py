from datetime import datetime
from decimal import Decimal

from sqlalchemy import Column, DateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB


class AmountMixin:
    amount: Decimal = Column(Numeric, nullable=False)
    time: datetime = Column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies: dict = Column(JSONB, nullable=True)

    #@orm.reconstructor
    #def init_on_load(self):
    #    self.error = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


