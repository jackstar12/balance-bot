import sqlalchemy as sa
from sqlalchemy import orm
from datetime import datetime

from sqlalchemy.ext.hybrid import hybrid_property

from balancebot.common import utils
from balancebot.common.database import Base
from balancebot.common.models.gain import Gain


balance_association = sa.Table(
    'balance_association', Base.metadata,
    sa.Column('balance_id', sa.ForeignKey('balance.id', ondelete="CASCADE"), primary_key=True),
    sa.Column('chapter_id', sa.ForeignKey('chapter.id', ondelete="CASCADE"), primary_key=True)
)


class Chapter(Base):
    __tablename__ = 'chapter'

    id = sa.Column(sa.Integer, primary_key=True)
    start_date = sa.Column(sa.Date, nullable=False)
    end_date = sa.Column(sa.Date, nullable=False)

    journal_id = sa.Column(sa.Integer,
                           sa.ForeignKey('journal.id', ondelete="CASCADE"),
                           nullable=False)
    #start_balance_id = sa.Column(sa.Integer, sa.ForeignKey('balance.id'), nullable=True)
    #end_balance_id = sa.Column(sa.Integer, sa.ForeignKey('balance.id'), nullable=True)

    balances = orm.relationship('Balance',
                                lazy='noload',
                                secondary=balance_association,
                                order_by='Balance.time')

    journal = orm.relationship('Journal', lazy='noload')
    #start_balance = orm.relationship('Balance', lazy='noload', foreign_keys=start_balance_id)
    #end_balance = orm.relationship('Balance', lazy='noload', foreign_keys=end_balance_id)

    #trades = orm.relationship('Trade',
    #                          lazy='noload',
    #                          primaryjoin="and_("
    #                                      #"Trade.client_id == Chapter.client_id, "
    #                                      "Trade.client_id.in_(select(guild_association.client_id).filter_by(),"
    #                                      "Execution.time.cast(Date) >= Chapter.start_date,"
    #                                      "Execution.time.cast(Date) <= Chapter.end_date"
    #                                      ")",
    #                          secondary="join(Execution, Trade, Execution.id == Trade.initial_execution_id)",
    #                          secondaryjoin="Execution.id == Trade.initial_execution_id",
    #                          viewonly=True,
    #                          uselist=True
    #                          )

    notes = sa.Column(sa.Text, nullable=True)

    @hybrid_property
    def performance(self) -> Gain:
        if self.balances:
            start_balance = self.balances[0]
            end_balance = self.balances[1]
            return Gain(
                relative=utils.calc_percentage(start_balance.total, end_balance.total, string=False),
                absolute=end_balance.realized - start_balance.realized
            )

