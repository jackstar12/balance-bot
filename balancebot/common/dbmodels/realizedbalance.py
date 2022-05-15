from sqlalchemy import Column
from sqlalchemy.orm import relationship

from balancebot.common.database import Base
from balancebot.common.dbmodels.amountmixin import AmountMixin
import sqlalchemy as sa


class RealizedBalance(Base, AmountMixin):
    __tablename__ = 'realizedbalance'

    id = sa.Column(sa.Integer, primary_key=True)
    client_id = sa.Column(sa.Integer, sa.ForeignKey('client.id'), nullable=False)
    client = sa.orm.relationship('Client', foreign_keys=client_id)
