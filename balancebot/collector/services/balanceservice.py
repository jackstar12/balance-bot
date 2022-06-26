import asyncio
import logging
from asyncio import Queue
from collections import deque
from typing import Dict, Optional, Deque, NamedTuple

from aioredis.client import Pipeline
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.job import Job
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from balancebot.collector.services.baseservice import BaseService
from balancebot.collector.services.dataservice import DataService, Channel
from balancebot.common import utils, customjson
from balancebot.common.dbasync import db_all, db_unique, db_eager, async_maker
from balancebot.common.dbmodels.chapter import Chapter
from balancebot.common.dbmodels.client import Client
from balancebot.common.dbmodels.journal import Journal
from balancebot.common.dbmodels.serializer import Serializer
from balancebot.common.dbmodels.trade import Trade
from balancebot.common.errors import InvalidClientError, ResponseError
from balancebot.common.exchanges.exchangeworker import ExchangeWorker
from balancebot.common.messenger import ClientUpdate
from balancebot.common.messenger import NameSpace, Category


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
            Client.discord_user,
            Client.currently_realized,
            Client.recent_history,
            Client.trades,
            (Client.open_trades, [Trade.max_pnl, Trade.min_pnl]),
            (Client.journals, (Journal.current_chapter, Chapter.balances))
        )
        self._active_client_stmt = self._all_client_stmt.join(
            Trade,
            and_(
                Client.id == Trade.client_id,
                Trade.open_qty > 0
            )
        )

        self._scheduler = AsyncIOScheduler(
            executors={
                'default': AsyncIOExecutor()
            }
        )

        self._exchange_jobs: Dict[str, ExchangeJob] = {}
        self._balance_queue = Queue()

        self._db: Optional[AsyncSession] = None
        self._base_db: Optional[AsyncSession] = None
        self._balance_session = None

    def __exit__(self):
        self._db.sync_session.close()
        self._base_db.sync_session.close()

    async def _initialize_positions(self):

        await self._messenger.sub_channel(NameSpace.TRADE, sub=Category.UPDATE, callback=self._on_trade_update, pattern=True)
        await self._messenger.sub_channel(NameSpace.TRADE, sub=Category.NEW, callback=self._on_trade_delete, pattern=True)

        await self._messenger.sub_channel(NameSpace.TRADE, sub=Category.FINISHED, callback=self._on_trade_delete,
                                    pattern=True)

        await self._messenger.sub_channel(NameSpace.CLIENT, sub=Category.NEW, callback=self._on_client_add, pattern=True)

        await self._messenger.sub_channel(NameSpace.CLIENT, sub=Category.DELETE, callback=self._on_client_delete, pattern=True)

        await self._messenger.sub_channel(NameSpace.CLIENT, sub=Category.UPDATE, callback=self._on_client_update, pattern=True)

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

            # await asyncio.gather(
            #     *[await self.add_client(client) for client in clients],
            #     return_exceptions=False
            # )

    def _remove_worker_by_id(self, client_id: int):
        self._remove_worker(self._get_existing_worker(client_id))

    def _get_existing_worker(self, client_id: int):
        return (
                self._base_workers_by_id.get(client_id)
                or
                self._premium_workers_by_id.get(client_id)
        )

    def _on_client_delete(self, data: Dict):
        self._remove_worker_by_id(data['id'])

    async def _on_client_add(self, data: Dict):
        await self._add_client_by_id(data['id'])

    async def _on_client_update(self, data: Dict):
        edit = ClientUpdate(**data)
        worker = self._get_existing_worker(edit.id)
        if worker:
            await self._db.refresh(worker.client)
        if edit.archived or edit.invalid:
            self._remove_worker(worker)
        elif edit.archived is False or edit.invalid is False:
            await self._add_client_by_id(edit.id)
        if edit.premium is not None:
            self._remove_worker(worker)
            await self._add_client_by_id(edit.id)

    async def _on_trade_new(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=True)
        if worker:
            await self._db.refresh(worker.client)
            # Trade is already contained in session because of ^^, no SQL will be emitted
            new = await self._db.get(Trade, data['trade_id'])
            await self.data_service.subscribe(worker.client.exchange, Channel.TICKER, symbol=new.symbol)

    async def _on_trade_update(self, data: Dict):
        client_id = data['client_id']
        trade_id = data['id']
        worker = await self.get_worker(client_id, create_if_missing=True)
        if worker:
            client = await self._db.get(Client, worker.client_id)
            for trade in client.open_trades:
                if trade.id == trade_id:
                    await self._db.refresh(trade)

    async def _on_trade_delete(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=False)
        if worker:
            await self._db.refresh(worker.client)
            if len(worker.client.open_trades) == 0:
                symbol = data['symbol']
                # If there are no trades on the same exchange matching the deleted symbol, there is no need to keep it subscribed
                unsubscribe_symbol = all(
                    trade.symbol != symbol
                    for cur_worker in self._premium_workers_by_id.values() if
                    cur_worker.client.exchange == worker.client.exchange
                    for trade in cur_worker.client.open_trades
                )
                if unsubscribe_symbol:
                    await self.data_service.unsubscribe(worker.client.exchange, Channel.TICKER, symbol=symbol)
                self._remove_worker(worker)

    async def _add_client_by_id(self, client_id: int):
        await self.add_client(
            await db_unique(self._all_client_stmt.filter_by(id=client_id), session=self._db)
        )

    def _add_worker(self, worker: ExchangeWorker, premium):
        workers = self._premium_workers_by_id if premium else self._base_workers_by_id
        if worker.client.id not in workers:
            workers[worker.client.id] = worker

            def worker_callback(category, sub_category):
                async def callback(worker: ExchangeWorker, obj: Serializer):
                    self._messenger.pub_channel(category, sub=sub_category,
                                                channel_id=worker.client_id,
                                                obj=await obj.serialize(full=False))

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

    def _remove_worker(self, worker: ExchangeWorker):
        asyncio.create_task(worker.disconnect())
        (self._premium_workers_by_id if worker.client.is_premium else self._base_workers_by_id).pop(worker.client.id,
                                                                                                    None)
        if not worker.client.is_premium:
            exchange_job = self._exchange_jobs[worker.exchange]
            exchange_job.deque.remove(worker)
            reschedule(exchange_job)

    async def add_client(self, client) -> Optional[ExchangeWorker]:
        exchange_cls = self._exchanges.get(client.exchange)
        if exchange_cls and issubclass(exchange_cls, ExchangeWorker):
            worker = exchange_cls(client,
                                self._http_session,
                                self._db if client.is_premium else self._base_db,
                                self._messenger,
                                self.rekt_threshold)
            if client.is_premium and exchange_cls.supports_extended_data:
                try:
                    await worker.synchronize_positions()
                    await worker.connect()
                except InvalidClientError:
                    return None
                except ResponseError:
                    logging.exception(f'Error while adding {client.id=}')
                self._add_worker(worker, premium=True)
            else:
                self._add_worker(worker, premium=False)
            return worker
        else:
            logging.error(
                f'CRITICAL: Exchange class {exchange_cls} for exchange {client.exchange} does NOT subclass ClientWorker')

    async def get_worker(self, client_id: int, create_if_missing=True) -> ExchangeWorker:
        if client_id:
            worker = self._base_workers_by_id.get(client_id) or self._premium_workers_by_id.get(client_id)
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
        async with async_maker() as _db, async_maker() as _base_db:
            self._db = _db
            self._base_db = _base_db
            await self._initialize_positions()
            await asyncio.gather(
                self._balance_updater(),
                self._balance_collector()
            )

    async def _balance_updater(self):
        while True:
            balances = []
            new_balances = []

            for worker in self._premium_workers_by_id.values():
                new = False
                client = worker.client
                for trade in client.open_trades:
                    ticker = self.data_service.get_ticker(trade.symbol, client.exchange)
                    if ticker:
                        trade.update_pnl(ticker.price, realtime=True, extra_currencies={'USD': ticker.price})
                        if inspect(trade.max_pnl).transient or inspect(trade.min_pnl).transient:
                            new = True
                balance = client.evaluate_balance(self._redis)
                if balance:
                    balances.append(balance)
                    # TODO: Introduce new mechanisms determining when to save
                    if new:
                        new_balances.append(balance)
            if new_balances:
                self._db.add_all(new_balances)
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
            await asyncio.sleep(0.2)

    async def _balance_collector(self):
        while True:
            balances = [await self._balance_queue.get()]

            await asyncio.sleep(2)
            while not self._balance_queue.empty():
                balances.append(self._balance_queue.get_nowait())

            self._base_db.add_all(balances)
            await self._base_db.commit()
