import sqlalchemy as sa


class CurrencyMixin:
    #raw = mapped_column(sa.String(10), nullable=False)
    settle = mapped_column(sa.String(5), nullable=False)
    inverse = mapped_column(sa.Boolean, default=False, nullable=False)

    #@hybrid_property
    #def symbol(self):
    #    return self.raw
