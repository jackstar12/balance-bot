from operator import and_

from sqlalchemy import desc, select, func, Date, join, or_, asc
from sqlalchemy.orm import relationship, aliased, foreign

import database.dbmodels.alert
import database.dbmodels.archive
import database.dbmodels.balance
import database.dbmodels.client
import database.dbmodels.coin
import database.dbmodels.discord.discorduser
import database.dbmodels.event
import database.dbmodels.execution
import database.dbmodels.journal
import database.dbmodels.label
import database.dbmodels.pnldata
import database.dbmodels.mixins.serializer
import database.dbmodels.trade
import database.dbmodels.transfer
import database.dbmodels.user
import database.dbmodels.chapter
import database.dbmodels.template
import database.dbmodels.score
import database.dbmodels.discord.guildassociation as ga
import database.dbmodels.action

Client = client.Client
User = user.User
BalanceDB = balance.Balance
Balance = balance.Balance
Chapter = chapter.Chapter
Execution = execution.Execution
TradeDB = trade.Trade
EventScore = score.EventScore
EventRank = score.EventRank
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
                                              TradeDB.open_time.cast(Date) >= Chapter.data['start_date'],
                                              TradeDB.open_time.cast(Date) <= Chapter.data['end_date']
                                          ),
                                          or_(
                                              TradeDB.client_id.in_(sub),
                                              TradeDB.id == chapter_trade_assoc.c.trade_id
                                          )
                                      ),
                                      secondary=join(Chapter, chapter_trade_assoc, chapter_trade_assoc.c.chapter_id == Chapter.id),
                                      secondaryjoin=chapter_trade_assoc.c.chapter_id == Chapter.id,
                                      viewonly=True,
                                      uselist=True
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


equ = and_(
    EventScore.client_id == foreign(EventRank.client_id),
    EventScore.event_id == foreign(EventRank.event_id)
)

current = select(
    EventRank
).order_by(
    desc(EventRank.time)
).limit(1).alias()

latest = aliased(EventRank, current)


#EventScore.current_rank = relationship(EventRank,
#                                       lazy='joined',
#                                       uselist=False
#                                       )
#EventScore.current_rank = relationship(latest, lazy='noload', uselist=False)


EventScore.rank_history = relationship(EventRank,
                                       lazy='noload',
                                       primaryjoin=equ,
                                       order_by=asc(EventRank.time))



__all__ = [
    "balance",
    "client",
    "trade",
    "user",
    "Client",
    "Execution",
    "TradeDB",
    "GuildAssociation"
]
