import sqlalchemy as sa
from sqlalchemy import orm
from datetime import datetime

from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.common import utils
from balancebot.common.database import Base
from balancebot.common.models.clientgain import Gain


class Chapter(Base):
    __tablename__ = 'chapter'

    id = sa.Column(sa.Integer, primary_key=True)
    start_date = sa.Column(sa.Date, nullable=False)
    end_date = sa.Column(sa.Date, nullable=False)

    journal_id = sa.Column(sa.Integer, sa.ForeignKey('journal.id'), nullable=False)
    client_id = sa.Column(sa.Integer, sa.ForeignKey('client.id'), nullable=False)
    start_balance_id = sa.Column(sa.Integer, sa.ForeignKey('balance.id'), nullable=True)
    end_balance_id = sa.Column(sa.Integer, sa.ForeignKey('balance.id'), nullable=True)

    journal = orm.relationship('Journal', lazy='noload')
    start_balance = orm.relationship('Balance', lazy='noload', foreign_keys=start_balance_id)
    end_balance = orm.relationship('Balance', lazy='noload', foreign_keys=end_balance_id)

    trades = orm.relationship('Trade',
                              lazy='noload',
                              primaryjoin="and_("
                                          "Trade.client_id == Chapter.client_id, "
                                          "Execution.time.cast(Date) >= Chapter.start_date,"
                                          "Execution.time.cast(Date) <= Chapter.end_date"
                                          ")",
                              secondary="join(Execution, Trade, Execution.id == Trade.initial_execution_id)",
                              secondaryjoin="Execution.id == Trade.initial_execution_id",
                              viewonly=True,
                              uselist=True
                              )

    notes = sa.Column(sa.Text, nullable=True)

    @hybrid_property
    def performance(self) -> Gain:
        return Gain(
            relative=utils.calc_percentage(self.start_balance.total, self.end_balance.total, string=False),
            absolute=self.end_balance - self.start_balance
        )

