from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Type

import discord
from sqlalchemy import select

from tradealpha.collector.services.baseservice import BaseService
from tradealpha.common.dbasync import db_all, db_select
from tradealpha.common.dbmodels import Execution
from tradealpha.common.dbmodels.action import Action, ActionType, ActionTrigger
from tradealpha.common.dbmodels.balance import Balance
from tradealpha.common.dbmodels.mixins.serializer import Serializer
from tradealpha.common.dbmodels.trade import Trade
from tradealpha.common.enums import Side
from tradealpha.common.models.discord.guild import MessageRequest
from tradealpha.common.redis import rpc


@dataclass
class FutureCallback:
    time: datetime
    callback: Callable


class ActionService(BaseService):

    @classmethod
    def get_embed(cls, fields: dict, **embed_kwargs):
        embed = discord.Embed(**embed_kwargs)
        for k, v in fields.items():
            embed.add_field(name=k, value=v)
        return embed

    @classmethod
    def to_embed(cls, table: Type[Serializer], data: dict):
        if table == Balance:
            return cls.get_balance_embed(Balance(**data))
        if table == Trade:
            return cls.get_trade_embed(Trade(**data))
        return None

    @classmethod
    def get_trade_embed(cls, trade: Trade):
        return cls.get_embed(
            title='Trade',
            fields={
                'Symbol': trade.symbol,
                'Side': 'Long' if trade.side == Side.BUY else 'Short',
                'Realized PNL': trade.realized_pnl,
                'Entry': trade.entry,
                'Exit': trade.exit,
                'Open Date': trade.open_time,
                'Close Date': trade.open_time,
            }
        )

    @classmethod
    def get_exec_embed(cls, execution: Execution):
        return cls.get_embed(
            title='Execution',
            fields={
                'Symbol': execution.symbol,
                'Realized PNL': execution.realized_pnl,
                'Type': execution.type,
                'Price': execution.price,
                'Size': execution.qty * execution.price
            }
        )

    @classmethod
    def get_balance_embed(cls, balance: Balance):
        return cls.get_embed(
            title='Balance',
            fields={
                'Realized': balance.realized,
                'Total': balance.total,
            }
        )

    def get_action(self, data: dict):
        return db_select(
            Action, Action.id == data['id']
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.action_sync = SyncedService(self._messenger,
        #                                  EVENT,
        #                                  get_stmt=self._get_event,
        #                                  update=self._get_event,
        #                                  cleanup=self._on_event_delete)

    async def update(self, action: Action):
        await self.remove(action)
        await self.add(action)

    def add(self, action: Action):
        return self._messenger.sub_channel(
            action.namespace,
            action.topic,
            lambda data: self.execute(action, data),
            **action.all_ids
        )

    def remove(self, action: Action):
        return self._messenger.unsub_channel(
            action.namespace,
            action.topic,
            **action.all_ids
        )

    async def execute(self, action: Action, data: dict):
        namespace = self._messenger.get_namespace(action.namespace)
        if action.action_type == ActionType.WEBHOOK:
            if action.extra.get('format') == 'discord':
                embed = self.to_embed(namespace.table, data)
                if embed:
                    send = embed.to_dict()
            url = action.extra['url']
            async with self._http_session.post(url) as response:
                if response.status_code == 200:
                    pass  # OK
        elif action.action_type == ActionType.DISCORD:
            dc = rpc.Client('discord', self._redis)
            embed = self.to_embed(namespace.table, data)
            await dc(
                'send',
                MessageRequest(
                    **action.extra,
                    embed=embed.to_dict() if embed else None
                )
            )

        if action.trigger_type == ActionTrigger.ONCE:
            await self.remove(action)
            await self._db.delete(action)

    async def init(self):
        for action in await db_all(select(Action)):
            await self.add(action)
        # await self.action_sync.sub()
