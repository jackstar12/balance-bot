from datetime import datetime
from decimal import Decimal

from sqlalchemy importDateTime, Numeric
from sqlalchemy.dialects.postgresql import JSONB


class AmountMixin:
    amount: Decimal = mapped_column(Numeric, nullable=False)
    time: datetime = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    extra_currencies: dict = mapped_column(JSONB, nullable=True)

    #@orm.reconstructor
    #def init_on_load(self):
    #    self.error = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


