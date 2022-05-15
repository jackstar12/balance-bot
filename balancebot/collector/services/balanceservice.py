import logging
from asyncio import Queue
from inspect import currentframe

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
from balancebot.common import utils
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
                await self._redis.mset({
                    utils.join_args(NameSpace.CLIENT, NameSpace.BALANCE, balance.client_id): balance.amount
                    for balance in balances
                })
            await asyncio.sleep(3 - (time.time() - ts))

    async def start_fetching(self):
        """
        Start fetching data at specified interval
        """
        while True:
            await self._async_fetch_data()
            time = datetime.now(pytz.utc)
            next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                                microsecond=0) + timedelta(hours=self.interval_hours)
            delay = next - time
            await asyncio.sleep(delay.total_seconds())

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

    async def get_client_balance(self,
                                 client: Client,
                                 currency: str = None,
                                 priority: Priority = Priority.HIGH,
                                 force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = await self._async_fetch_data(workers=[await self.get_worker(client.id)], keep_errors=True,
                                            priority=priority,
                                            force_fetch=force_fetch)

        if data:
            result = data[0]
            # if result.error is None or result.error == '':
            #     matched_balance = db_match_balance_currency(result, currency)
            #     if matched_balance:
            #         result = matched_balance
            #     else:
            #         result.error = f'User balance does not contain currency {currency}'
        else:
            result = await client.latest()

        return result

    async def clear_client_data(self,
                                client: Client,
                                start: datetime = None,
                                end: datetime = None,
                                update_initial_balance=False):
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now(pytz.utc)

        await db(
            delete(Balance).filter(
                Balance.client_id == client.id,
                Balance.time >= start,
                Balance.time <= end
            ),
            session=self._db
        )

        history_record = await db_first(client.history.statement, session=self._db)
        if not history_record and update_initial_balance:
            client.rekt_on = None
            asyncio.create_task(self.get_client_balance(client, force_fetch=True))

        await self._db.commit()

    async def _async_fetch_data(self, workers: List[ExchangeWorker] = None,
                                keep_errors: bool = False,
                                priority: Priority = Priority.MEDIUM,
                                force_fetch=False) -> List[Balance]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to guild entries with Balance objects (non-errors only)
        """
        time = datetime.now(tz=pytz.UTC)

        if workers is None:
            workers = list(self._base_workers_by_id.values())

        data = []
        tasks = []

        logging.info(f'Fetching data for {len(workers)} workers {keep_errors=}')
        results = await asyncio.gather(*[
            worker.get_balance(date=time, priority=priority, force=force_fetch)
            for worker in workers if (worker and worker.in_position) or force_fetch
        ])

        return results

        tasks = []
        for result in results:
            if isinstance(result, Balance):
                client = await db_select(Client, id=result.client_id, session=self._db)
                if client:
                    tasks.append(
                        lambda: self._messenger.pub_channel(NameSpace.BALANCE, Category.NEW, channel_id=client.id,
                                                            obj=result.id)
                    )
                    history = await db_all(client.history.order_by(desc(Balance.time)).limit(3), session=self._db)
                    history_len = len(history)
                    latest_balance = None if history_len == 0 else history[history_len - 1]
                    if history_len > 2:
                        # If balance hasn't changed at all, why bother keeping it?
                        if math.isclose(latest_balance.amount, result.amount, rel_tol=1e-06) \
                                and math.isclose(history[history_len - 2].amount, result.amount, rel_tol=1e-06):
                            latest_balance.time = time
                            data.append(latest_balance)
                            continue
                    if result.error:
                        logging.error(f'Error while fetching {client.id=} balance: {result.error}')
                        if keep_errors:
                            data.append(result)
                    else:
                        self._db.add(result)
                        data.append(result)
                        if result.amount <= self.rekt_threshold and not client.rekt_on:
                            client.rekt_on = time
                            self._messenger.pub_channel(NameSpace.CLIENT, Category.REKT, channel_id=client.id,
                                                        obj={'id': client.id})
                else:
                    logging.error(f'Worker with {result.client_id=} got no client object!')

        await self._db.commit()

        for task in tasks:
            task()

        logging.info(f'Done Fetching')
        return data
