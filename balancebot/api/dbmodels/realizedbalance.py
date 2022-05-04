from balancebot.api.database import Base
from balancebot.api.dbmodels.amountmixin import AmountMixin


class RealizedBalance(Base, AmountMixin):
    __tablename__ = 'realizedbalance'

    #id = Column()
