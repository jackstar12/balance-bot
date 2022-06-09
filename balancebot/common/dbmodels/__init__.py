from operator import and_

from sqlalchemy import desc, select, func, Date, join, or_
from sqlalchemy.orm import relationship, aliased

import balancebot.common.dbmodels.alert
import balancebot.common.dbmodels.archive
import balancebot.common.dbmodels.balance
import balancebot.common.dbmodels.client
import balancebot.common.dbmodels.coin
import balancebot.common.dbmodels.discorduser
import balancebot.common.dbmodels.event
import balancebot.common.dbmodels.execution
import balancebot.common.dbmodels.guild
import balancebot.common.dbmodels.guildassociation
import balancebot.common.dbmodels.journal
import balancebot.common.dbmodels.label
import balancebot.common.dbmodels.pnldata
import balancebot.common.dbmodels.serializer
import balancebot.common.dbmodels.trade
import balancebot.common.dbmodels.transfer
import balancebot.common.dbmodels.user
import balancebot.common.dbmodels.chapter

Client = client.Client
Balance = balance.Balance
Chapter = chapter.Chapter
Execution = execution.Execution
Trade = trade.Trade

partioned_balance = select(
    Balance,
    func.row_number().over(
        order_by=desc(Balance.time), partition_by=Balance.client_id
    ).label('index')
).alias()

partioned_history = aliased(Balance, partioned_balance)

client.Client.recent_history = relationship(
    partioned_history,
    lazy='noload',
    primaryjoin=and_(client.Client.id == partioned_history.client_id, partioned_balance.c.index <= 3)
)

journal_assoc = journal.journal_association
chapter_trade_assoc = chapter.chapter_trade_association

sub = select(
    Client.id
).join(
    journal_assoc,
    and_(
        journal_assoc.c.client_id == Client.id,
        journal_assoc.c.journal_id == Chapter.journal_id
    )
)

chapter.Chapter.trades = relationship('Trade',
                                      lazy='noload',
                                      primaryjoin=and_(
                                          and_(
                                              Trade.open_time.cast(Date) >= Chapter.start_date,
                                              Trade.open_time.cast(Date) <= Chapter.end_date
                                          ),
                                          or_(
                                              Trade.client_id.in_(sub),
                                              Trade.id == chapter_trade_assoc.c.trade_id
                                          )
                                      ),
                                      secondary=join(Chapter, chapter_trade_assoc, chapter_trade_assoc.c.chapter_id == Chapter.id),
                                      secondaryjoin=chapter_trade_assoc.c.chapter_id == Chapter.id,
                                      viewonly=True,
                                      uselist=True
                                      )

__all__ = [
    "balance",
    "client",
    "trade",
    "user",
    "Client",
    "Execution",
    "Trade"
]
