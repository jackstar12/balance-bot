from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Type

import discord
from sqlalchemy import select

from database.dbmodels import Execution
from database.dbmodels.mixins.serializer import Serializer
from database.dbmodels.action import Action, ActionType
from database.models.discord.guild import MessageRequest
from database.redis import rpc
from collector.services.baseservice import BaseService
from database.dbasync import db_all, db_select

from database.dbmodels.balance import Balance
from database.dbmodels.trade import Trade



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

    @classmethod
    def get_trade_embed(cls, trade: Trade):
        return cls.get_embed(
            title='Trade',
            fields={
                'Symbol': trade.symbol,
                'Realized PNL': trade.realized_pnl,
                'Entry': trade.entry,
                'Exit': trade.exit
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

    async def add(self, action: Action):
        await self._messenger.v2_sub_channel(
            self._messenger.get_namespace(action.namespace),
            action.topic,
            lambda data: self.execute(action, data),
            **action.all_ids
        )

    async def remove(self, action: Action):
        await self._messenger.v2_unsub_channel(
            self._messenger.get_namespace(action.namespace),
            action.topic,
            **action.all_ids
        )

    async def execute(self, action: Action, data: dict):
        messenger_space = self._messenger.get_namespace(action.namespace)
        if action.action_type == ActionType.WEBHOOK:
            url = action.extra['url']
            # call
        elif action.action_type == ActionType.DISCORD:
            dc = rpc.Client('discord', self._redis)
            await dc(
                'send',
                MessageRequest(
                    **action.extra,
                    embed=self.to_embed(messenger_space.table, data).to_dict()
                )
            )

    async def init(self):
        for action in await db_all(select(Action)):
            await self.add(action)
        # await self.action_sync.sub()
