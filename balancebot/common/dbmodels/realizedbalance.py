from balancebot.common.database import Base
from balancebot.common.dbmodels.amountmixin import AmountMixin
import sqlalchemy as sa


class RealizedBalance(Base, AmountMixin):
    __tablename__ = 'realizedbalance'

    id = sa.Column(sa.Integer, primary_key=True)
