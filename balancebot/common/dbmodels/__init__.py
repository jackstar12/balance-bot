from operator import and_

from sqlalchemy import desc, select, func
from sqlalchemy.orm import relationship, aliased

import balancebot.common.dbmodels.alert
import balancebot.common.dbmodels.archive
import balancebot.common.dbmodels.client
import balancebot.common.dbmodels.event
import balancebot.common.dbmodels.discorduser
import balancebot.common.dbmodels.coin
import balancebot.common.dbmodels.guild
import balancebot.common.dbmodels.execution
import balancebot.common.dbmodels.guildassociation
import balancebot.common.dbmodels.label
import balancebot.common.dbmodels.pnldata
import balancebot.common.dbmodels.realizedbalance
import balancebot.common.dbmodels.serializer
import balancebot.common.dbmodels.trade
import balancebot.common.dbmodels.transfer
import balancebot.common.dbmodels.user
import balancebot.common.dbmodels.balance


cl = client.Client
bal = balance.Balance

partioned_balance = select(
    bal,
    func.row_number().over(
        order_by=desc(bal.time), partition_by=bal.client_id
    ).label('index')
).alias()

partioned_history = aliased(bal, partioned_balance)

client.Client.recent_history = relationship(
    partioned_history,
    lazy='noload',
    primaryjoin=and_(client.Client.id == partioned_history.client_id, partioned_balance.c.index <= 3)
)


__all__ = [
    "balance",
    "client",
    "trade",
    "user"
]
