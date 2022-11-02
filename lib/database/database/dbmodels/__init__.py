from operator import and_

from sqlalchemy import desc, select, func, Date, join, or_, asc
from sqlalchemy.orm import relationship, aliased, foreign

import database.dbmodels.alert
import database.dbmodels.balance
import database.dbmodels.client
import database.dbmodels.coin
import database.dbmodels.event
import database.dbmodels.execution
import database.dbmodels.label
import database.dbmodels.pnldata
import database.dbmodels.mixins.serializer
import database.dbmodels.trade
import database.dbmodels.transfer
import database.dbmodels.user
import database.dbmodels.score
import database.dbmodels.action

import database.dbmodels.editing.chapter as chapter
import database.dbmodels.editing.template as template
import database.dbmodels.editing.journal as journal

import database.dbmodels.discord.discorduser
import database.dbmodels.discord.guild as guild
import database.dbmodels.discord.guildassociation as ga
import database.dbmodels.authgrant

Client = client.Client
User = user.User
BalanceDB = balance.Balance
Balance = balance.Balance
Chapter = chapter.Chapter
Execution = execution.Execution
TradeDB = trade.Trade
EventEntry = score.EventEntry
EventScore = score.EventScore
Event = event.Event
GuildAssociation = ga.GuildAssociation

partioned_balance = select(
    BalanceDB,
    func.row_number().over(
        order_by=desc(BalanceDB.time), partition_by=BalanceDB.client_id
    ).label('index')
).alias()

partioned_history = aliased(BalanceDB, partioned_balance)

client.Client.recent_history = relationship(
    partioned_history,
    lazy='noload',
    primaryjoin=and_(client.Client.id == partioned_history.client_id, partioned_balance.c.index <= 3)
)

#ChildChapter = aliased(Chapter)
#child_ids = select(ChildChapter.id)
#
#query = aliased(Chapter, child_ids)
#
#Chapter.child_ids = relationship(
#    query,
#    lazy='noload',
#    primaryjoin=ChildChapter.parent_id == Chapter.id,
#    viewonly=True,
#    uselist=True
#)


current = select(
    EventScore
).order_by(
    desc(EventScore.time)
).limit(1).alias()

latest = aliased(EventScore, current)


#EventScore.current_rank = relationship(EventRank,
#                                       lazy='joined',
#                                       uselist=False
#                                       )
#EventScore.current_rank = relationship(latest, lazy='noload', uselist=False)





__all__ = [
    "balance",
    "Balance",
    "BalanceDB",
    "client",
    "trade",
    "user",
    "Client",
    "Execution",
    "TradeDB",
    "GuildAssociation"
]
