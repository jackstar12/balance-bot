import logging
from asyncio import Queue
from inspect import currentframe

from aioredis.client import Pipeline
from apscheduler.job import Job
from sqlalchemy import select, delete, and_
from sqlalchemy.inspection import inspect
import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Deque, NamedTuple, Generic, Type

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.triggers.interval import IntervalTrigger
from collections import deque
import pytz

from balancebot.common.database_async import db_all, db_first, db, db_unique, db_eager, async_maker
from balancebot.common.dbmodels.balance import Balance
from balancebot.common.dbmodels.client import Client
from balancebot.common.dbmodels.discorduser import DiscordUser
from balancebot.common.dbmodels.pnldata import PnlData
from balancebot.common.dbmodels.serializer import Serializer
from balancebot.common.dbmodels.trade import Trade
from balancebot.collector.services.baseservice import BaseService
from balancebot.collector.services.dataservice import DataService, Channel
from balancebot.common import utils, customjson
from balancebot.common.enums import Priority
from balancebot.common.messenger import NameSpace, Category
from balancebot.common.messenger import ClientEdit
from balancebot.common.exchanges.exchangeworker import ExchangeWorker


class ExchangeJob(NamedTuple):
    exchange: str
    job: Job
    deque: Deque[ExchangeWorker]


def reschedule(exchange_job: ExchangeJob):
    trigger = IntervalTrigger(seconds=15 // (len(exchange_job.deque) or 1))
    exchange_job.job.reschedule(trigger)


class BalanceService(BaseService):

    def __init__(self,
                 *args,
                 data_service: DataService,
                 exchanges: dict = None,
                 rekt_threshold: float = 2.5,
                 data_path: str = '',
                 **kwargs):
        super().__init__(*args, **kwargs)

        # Public parameters
        self.rekt_threshold = rekt_threshold
        self.data_path = data_path
        self.backup_path = self.data_path + 'backup/'

        self.data_service = data_service
        self._exchanges = exchanges
        self._base_workers_by_id: Dict[int, ExchangeWorker] = {}
        self._premium_workers_by_id: Dict[int, ExchangeWorker] = {}

        self._trades_by_id: Dict[int, Trade] = {}
        self._trades_by_client_id: Dict[int, Dict] = {}
        self._clients_by_id: Dict[int, Client] = {}

        self._all_client_stmt = db_eager(
            select(Client).filter(
                Client.archived == False,
                Client.invalid == False
            ),
            (Client.open_trades, [Trade.max_pnl, Trade.min_pnl]),
            Client.discord_user,
            Client.currently_realized,
        )
        self._active_client_stmt = self._all_client_stmt.join(
            Trade,
            and_(
                Client.id == Trade.client_id,
                Trade.open_qty > 0.0
            )
        )

        self._scheduler = AsyncIOScheduler(
            executors={
                'default': AsyncIOExecutor()
            }
        )

        self._exchange_jobs: Dict[str, ExchangeJob] = {}
        self._balance_queue = Queue()

        self._db = async_maker()
        self._balance_session = None
        self._scheduler.start()

    async def _initialize_positions(self):

        self._messenger.sub_channel(NameSpace.TRADE, sub=Category.UPDATE, callback=self._on_trade_update, pattern=True)
        self._messenger.sub_channel(NameSpace.TRADE, sub=Category.NEW, callback=self._on_trade_delete, pattern=True)
        self._messenger.sub_channel(NameSpace.TRADE, sub=Category.FINISHED, callback=self._on_trade_delete,
                                    pattern=True)

        self._messenger.sub_channel(NameSpace.CLIENT, sub=Category.NEW, callback=self._on_client_add)
        self._messenger.sub_channel(NameSpace.CLIENT, sub=Category.DELETE, callback=self._on_client_delete)

        clients = await db_all(self._all_client_stmt, session=self._db)

        for exchange in self._exchanges:
            exchange_queue = deque()
            job = self._scheduler.add_job(
                self.update_worker_queue,
                IntervalTrigger(seconds=3600),
                args=(exchange_queue,)
            )
            self._exchange_jobs[exchange] = ExchangeJob(exchange, job, exchange_queue)

        for client in clients:
            await self.add_client(client)

    def _on_client_delete(self, data: Dict):
        self._remove_worker(self._base_workers_by_id.get(data['id']))

    async def _on_client_add(self, data: Dict):
        await self._add_client_by_id(data['id'])

    async def _on_client_edit(self, data: Dict):
        edit = ClientEdit(**data)
        if edit.archived or edit.invalid:
            self._remove_worker(await self.get_worker(edit.id, create_if_missing=False))
        elif edit.archived is False or edit.invalid is False:
            await self._add_client_by_id(edit.id)

    async def _on_trade_new(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=True)
        if worker:
            await self._db.refresh(worker.client.open_trades)
            # Trade is already contained in session because of ^^, no SQL will be emitted
            new = await self._db.get(Trade, data['trade_id'])
            await self.data_service.subscribe(worker.client.exchange, Channel.TICKER, symbol=new.symbol)

    async def _on_trade_update(self, data: Dict):
        client_id = data['client_id']
        trade_id = data['trade_id']
        worker = await self.get_worker(client_id, create_if_missing=True)
        if worker:
            for trade in worker.client.open_trades:
                if trade.id == trade_id:
                    await self._db.refresh(trade)

    async def _on_trade_delete(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=False)
        if worker:
            await self._db.refresh(worker.client.open_trades)
            if len(worker.client.open_trades) == 0:
                symbol = data['symbol']
                # If there are no trades on the same exchange matching the deleted symbol, there is no need to keep it subscribed
                unsubscribe_symbol = all(
                    trade.symbol != symbol
                    for cur_worker in self._premium_workers_by_id.values() if cur_worker.client.exchange == worker.client.exchange
                    for trade in cur_worker.client.open_trades
                )
                if unsubscribe_symbol:
                    await self.data_service.unsubscribe(worker.client.exchange, Channel.TICKER, symbol=symbol)
                self._remove_worker(worker)

    async def _add_client_by_id(self, client_id: int):
        await self.add_client(
            await db_unique(self._all_client_stmt.filter_by(id=client_id), session=self._db)
        )

    def _add_worker(self, worker: ExchangeWorker):
        premium = worker.client.is_premium
        workers = self._premium_workers_by_id if premium else self._base_workers_by_id
        if worker.client.id not in workers:
            workers[worker.client.id] = worker

            def worker_callback(category, sub_category):
                async def callback(worker: ExchangeWorker, obj: Serializer):
                    self._messenger.pub_channel(category, sub=sub_category,
                                                channel_id=worker.client_id, obj=await obj.serialize(full=False))

                return callback

            worker.set_trade_update_callback(
                worker_callback(NameSpace.TRADE, Category.UPDATE)
            )
            worker.set_trade_callback(
                worker_callback(NameSpace.TRADE, Category.NEW)
            )
            worker.set_balance_callback(
                worker_callback(NameSpace.BALANCE, Category.NEW)
            )

            if not premium:
                exchange_job = self._exchange_jobs[worker.exchange]
                exchange_job.deque.append(worker)
                reschedule(exchange_job)

    def _remove_worker(self, worker: ExchangeWorker, premium=False):
        asyncio.create_task(worker.disconnect())
        (self._premium_workers_by_id if premium else self._base_workers_by_id).pop(worker.client.id, None)
        if not premium:
            exchange_job = self._exchange_jobs[worker.exchange]
            exchange_job.deque.remove(worker)
            reschedule(exchange_job)

    async def add_client(self, client) -> Optional[ExchangeWorker]:
        client_cls = self._exchanges.get(client.exchange)
        if issubclass(client_cls, ExchangeWorker):
            worker = client_cls(client, self._http_session, self._messenger, self.rekt_threshold)
            if client.is_premium:
                await worker.synchronize_positions(db_session=self._db)
                await worker.connect()
            self._add_worker(worker)
            return worker
        else:
            logging.error(
                f'CRITICAL: Exchange class {client_cls} for exchange {client.exchange} does NOT subclass ClientWorker')

    async def get_worker(self, client_id: int, create_if_missing=True) -> ExchangeWorker:
        if client_id:
            worker = self._base_workers_by_id.get(client_id)
            if not worker and create_if_missing:
                await self._add_client_by_id(client_id)
            return worker

    async def update_worker_queue(self, worker_queue: Deque[ExchangeWorker]):
        if worker_queue:
            worker = worker_queue[0]
            balance = await worker.intelligent_get_balance(commit=False, db_session=self._balance_session)
            if balance:
                await self._balance_queue.put(balance)
            worker_queue.rotate()

    async def run_forever(self):
        await self._initialize_positions()

        asyncio.create_task(self._balance_collector())

        while True:
            ts = time.time()
            changes = False

            balances = []

            for worker in self._premium_workers_by_id.values():
                new = False
                for trade in worker.client.open_trades:
                    ticker = self.data_service.get_ticker(trade.symbol, trade.client.exchange)
                    if ticker:
                        trade.update_pnl(ticker.price, realtime=True)
                        if inspect(trade.max_pnl).transient or inspect(trade.min_pnl).transient:
                            new = True
                balance = await worker.client.evaluate_balance(self._redis)
                balances.append(balance)
                # TODO: Introduce new mechanisms determining when to save
                if new:
                    self._db.add(balance)
            await self._db.commit()
            if balances:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe: Pipeline = pipe
                    s = await balance.serialize(data=False, full=False)
                    for balance in balances:
                        await pipe.hset(
                            name=utils.join_args(NameSpace.CLIENT, balance.client_id),
                            key=NameSpace.BALANCE.value,
                            value=customjson.dumps(await balance.serialize(data=False, full=False))
                        )
                    await pipe.execute()
                #await self._redis.mset({
                #    utils.join_args(NameSpace.CLIENT, NameSpace.BALANCE, balance.client_id): str(balance.unrealized)
                #    for balance in balances
                #})
            await asyncio.sleep(3 - (time.time() - ts))

    async def _balance_collector(self):
        async with async_maker() as session:
            self._balance_session = session
            while True:
                balances = [await self._balance_queue.get()]

                await asyncio.sleep(2)

                while not self._balance_queue.empty():
                    balances.append(self._balance_queue.get_nowait())

                session.add_all(balances)
                await session.commit()
