import sqlalchemy as sa
from sqlalchemy.ext.hybrid import hybrid_property


class CurrencyMixin:
    #raw = sa.Column(sa.String(10), nullable=False)
    settle = sa.Column(sa.String(5), default='USD', nullable=False)
    inverse = sa.Column(sa.Boolean, default=False, nullable=False)

    #@hybrid_property
    #def symbol(self):
    #    return self.raw