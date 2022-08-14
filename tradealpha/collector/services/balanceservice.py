import abc
import asyncio
from asyncio import Queue
from collections import deque
from typing import Dict, Optional, Deque, NamedTuple

from aioredis.client import Pipeline
from apscheduler.job import Job
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.inspection import inspect

from tradealpha.common.config import DATA_PATH, REKT_THRESHOLD
from tradealpha.common.exchanges import EXCHANGES
from tradealpha.collector.services.baseservice import BaseService
from tradealpha.collector.services.dataservice import DataService, Channel
from tradealpha.common import utils, customjson
from tradealpha.common.dbasync import db_all, db_unique, db_eager
from tradealpha.common.dbmodels.chapter import Chapter
from tradealpha.common.dbmodels.client import Client
from tradealpha.common.dbmodels.journal import Journal
from tradealpha.common.dbmodels.trade import Trade
from tradealpha.common.errors import InvalidClientError, ResponseError, ClientDeletedError
from tradealpha.common.exchanges.exchangeworker import ExchangeWorker
from tradealpha.common.messenger import ClientUpdate
from tradealpha.common.messenger import NameSpace, Category


class ExchangeJob(NamedTuple):
    exchange: str
    job: Job
    deque: Deque[ExchangeWorker]


class Lock:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class _BalanceServiceBase(BaseService):

    def __init__(self,
                 *args,
                 data_service: DataService,
                 **kwargs):
        super().__init__(*args, **kwargs)

        # Public parameters
        self.rekt_threshold = REKT_THRESHOLD
        self.data_path = DATA_PATH
        self.backup_path = self.data_path + 'backup/'

        self.data_service = data_service
        self._exchanges = EXCHANGES
        self._workers_by_id: Dict[int, ExchangeWorker] = {}
        self._worker_lock = asyncio.Lock()
        #self._worker_lock = Lock()

        self._all_client_stmt = db_eager(
            select(Client).filter(
                Client.archived == False,
                Client.invalid == False
            ),
            Client.discord_user,
            Client.currently_realized,
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

    @classmethod
    def is_valid(cls, worker: ExchangeWorker, category: Category):
        if category == Category.ADVANCED:
            return worker.client.is_premium and worker.supports_extended_data
        elif category == Category.BASIC:
            return not (worker.client.is_premium and worker.supports_extended_data)

    async def _sub_client(self):
        await self._messenger.sub_channel(NameSpace.CLIENT,
                                          sub=Category.NEW,
                                          callback=self._on_client_add,
                                          pattern=True)

        await self._messenger.sub_channel(NameSpace.CLIENT,
                                          sub=Category.DELETE,
                                          callback=self._on_client_delete,
                                          pattern=True)

        await self._messenger.sub_channel(NameSpace.CLIENT,
                                          sub=Category.UPDATE,
                                          callback=self._on_client_update,
                                          pattern=True)

    async def _on_client_delete(self, data: Dict):
        await self._remove_worker_by_id(data['id'])
        await self._messenger.pub_channel(NameSpace.CLIENT, Category.REMOVED, data)

    async def _on_client_add(self, data: Dict):
        await self.add_client_by_id(data['id'])
        self._messenger.pub_channel(NameSpace.CLIENT, Category.ADDED, data)

    async def _refresh_worker(self, worker: ExchangeWorker):
        async with self._db_lock:
            await db_unique(
                self._all_client_stmt
                    .filter_by(id=worker.client_id)
                    .execution_options(populate_existing=True),
                session=self._db
            )

    async def _on_client_update(self, data: Dict):
        edit = ClientUpdate(**data)
        worker = self._get_existing_worker(edit.id)
        if worker:
            await self._refresh_worker(worker)
        if edit.archived or edit.invalid:
            await self._remove_worker(worker)
        elif edit.archived is False or edit.invalid is False:
            await self.add_client_by_id(edit.id)
        if edit.premium is not None:
            await self._remove_worker(worker)
            await self.add_client_by_id(edit.id)

    async def _remove_worker_by_id(self, client_id: int):
        worker = self._get_existing_worker(client_id)
        if worker:
            await self._remove_worker(worker)

    def _get_existing_worker(self, client_id: int):
        return self._workers_by_id.get(client_id)

    async def add_client_by_id(self, client_id: int):
        async with self._db_lock:
            client = await db_unique(
                self._all_client_stmt.filter_by(id=client_id),
                session=self._db
            )
        if client:
            await self.add_client(client)
        else:
            raise ValueError(f'Invalid {client_id=} passed in')

    async def add_client(self, client: Client) -> Optional[ExchangeWorker]:
        if client:
            exchange_cls = self._exchanges.get(client.exchange)
            if exchange_cls and issubclass(exchange_cls, ExchangeWorker):
                worker = exchange_cls(client,
                                      http_session=self._http_session,
                                      db_maker=self._db_maker,
                                      messenger=self._messenger,
                                      rekt_threshold=self.rekt_threshold)
                await self._add_worker(worker)
                return worker
            else:
                self._logger.error(f'Exchange class {exchange_cls} does NOT subclass ExchangeWorker')

    async def __aexit__(self, *args):
        await super().__aexit__(*args)
        for worker in self._workers_by_id.values():
            await self._remove_worker(worker)
            await worker.cleanup()

    @abc.abstractmethod
    async def _remove_worker(self, worker: ExchangeWorker):
        pass

    @abc.abstractmethod
    async def _add_worker(self, worker: ExchangeWorker):
        pass


class BasicBalanceService(_BalanceServiceBase):
    client_sub_category = Category.BASIC

    def __init__(self,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._exchange_jobs: Dict[str, ExchangeJob] = {}
        self._balance_queue = Queue()

    @staticmethod
    def reschedule(exchange_job: ExchangeJob):
        trigger = IntervalTrigger(seconds=15 // (len(exchange_job.deque) or 1))
        exchange_job.job.reschedule(trigger)

    async def _add_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            if worker.client.id not in self._workers_by_id and self.is_valid(worker, Category.BASIC):
                self._workers_by_id[worker.client.id] = worker

                exchange_job = self._exchange_jobs[worker.exchange]
                exchange_job.deque.append(worker)
                self.reschedule(exchange_job)

    async def _remove_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            self._workers_by_id.pop(worker.client.id,
                                    None)
            exchange_job = self._exchange_jobs[worker.exchange]
            exchange_job.deque.remove(worker)
            self.reschedule(exchange_job)

    async def update_worker_queue(self, worker_queue: Deque[ExchangeWorker]):
        if worker_queue:
            worker = worker_queue[0]
            balance = await worker.intelligent_get_balance()
            if balance:
                await self._balance_queue.put(balance)
            worker_queue.rotate()

    async def init(self):

        await self._sub_client()

        for exchange in self._exchanges:
            exchange_queue = deque()
            job = self._scheduler.add_job(
                self.update_worker_queue,
                IntervalTrigger(seconds=3600),
                args=(exchange_queue,)
            )
            self._exchange_jobs[exchange] = ExchangeJob(exchange, job, exchange_queue)

        for client in await db_all(
                self._all_client_stmt.filter(
                    or_(
                        Client.is_premium == False,
                        Client.exchange.in_([
                            ExchangeCls.exchange for ExchangeCls in self._exchanges.values()
                            if not ExchangeCls.supports_extended_data
                        ])
                    )
                ),
                session=self._db
        ):
            try:
                await self.add_client(client)
            except Exception:
                # TODO: Schedule retry?
                continue

    async def run_forever(self):
        while True:
            # For efficiency reasons, balances are always grouped in 2-second intervals
            # (less commits to database)
            balances = [await self._balance_queue.get()]

            await asyncio.sleep(2)
            while not self._balance_queue.empty():
                balances.append(self._balance_queue.get_nowait())

            self._db.add_all(balances)
            await self._db.commit()

            for balance in balances:
                self._messenger.pub_channel(NameSpace.BALANCE, Category.NEW, channel_id=balance.client_id.id,
                                            obj={'id': balance.id})


class ExtendedBalanceService(_BalanceServiceBase):
    client_sub_category = Category.ADVANCED

    async def init(self):
        await self._sub_client()

        await self._messenger.sub_channel(NameSpace.TRADE, sub=Category.UPDATE, callback=self._on_trade_update,
                                          pattern=True)

        await self._messenger.sub_channel(NameSpace.TRADE, sub=Category.NEW, callback=self._on_trade_new,
                                          pattern=True)

        await self._messenger.sub_channel(NameSpace.TRADE, sub=Category.FINISHED, callback=self._on_trade_finished,
                                          pattern=True)

        for client in await db_all(
                self._all_client_stmt.filter(
                    Client.is_premium == True,
                    Client.exchange.in_([
                        ExchangeCls.exchange for ExchangeCls in self._exchanges.values()
                        if ExchangeCls.supports_extended_data
                    ])
                ),
                session=self._db
        ):
            await self.add_client(client)

    async def _on_trade_new(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=True)
        if worker:
            await self._refresh_worker(worker)
            await self.data_service.subscribe(worker.client.exchange, Channel.TICKER, symbol=data['symbol'])

    async def _on_trade_update(self, data: Dict):
        client_id = data['client_id']

        worker = await self.get_worker(client_id, create_if_missing=True)
        if worker:
            await self._refresh_worker(worker)
            #async with self._db_lock:
            #    trade = await self._db.get(Trade, trade_id)
            #    await self._db.refresh(trade)

    async def _on_trade_finished(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=False)
        if worker:
            await self._refresh_worker(worker)
            if len(worker.client.open_trades) == 0:
                symbol = data['symbol']
                # If there are no trades on the same exchange matching the deleted symbol, there is no need to keep it subscribed
                unsubscribe_symbol = all(
                    trade.symbol != symbol
                    for cur_worker in self._workers_by_id.values() if
                    cur_worker.client.exchange == worker.client.exchange
                    for trade in cur_worker.client.open_trades
                )
                if unsubscribe_symbol:
                    await self.data_service.unsubscribe(worker.client.exchange, Channel.TICKER, symbol=symbol)
                await self._remove_worker(worker)

    async def _add_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            workers = self._workers_by_id
            if worker.client.id in workers:
                return

        if self.is_valid(worker, Category.ADVANCED):
            try:
                await worker.synchronize_positions()
                await worker.startup()
            except InvalidClientError:
                print(f'Error while adding {worker.client_id=}')
                return None
            except ResponseError:
                self._logger.exception(f'Error while adding {worker.client_id=}')
                print(f'Error while adding {worker.client_id=}')
                raise
            except Exception:
                self._logger.exception(f'Error while adding {worker.client_id=}')
                print(f'Error while adding {worker.client_id=}')
                raise

        async with self._worker_lock:
            self._workers_by_id[worker.client.id] = worker

    async def _remove_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            self._workers_by_id.pop(worker.client.id, None)
        await worker.cleanup()

    async def get_worker(self, client_id: int, create_if_missing=True) -> ExchangeWorker:
        async with self._worker_lock:
            if client_id:
                worker = self._workers_by_id.get(client_id)
                if not worker and create_if_missing:
                    await self.add_client_by_id(client_id)
                return worker

    async def run_forever(self):
        while True:
            balances = []

            async with self._db_lock, self._worker_lock:

                for worker in self._workers_by_id.values():
                    try:
                        client = await worker.get_client(self._db)
                    except ClientDeletedError:
                        continue
                    if client:
                        for trade in client.open_trades:
                            ticker = self.data_service.get_ticker(trade.symbol, client.exchange)
                            if ticker:
                                trade.update_pnl(
                                    trade.calc_upnl(ticker.price),
                                    realtime=True, extra_currencies={'USD': ticker.price}
                                )
                        balance = client.evaluate_balance()
                        if balance:
                            balances.append(balance)
                await self._db.commit()
            if balances:
                async with self._redis.pipeline(transaction=True) as pipe:
                    pipe: Pipeline = pipe
                    for balance in balances:
                        await pipe.hset(
                            name=utils.join_args(NameSpace.CLIENT, balance.client_id),
                            key=NameSpace.BALANCE.value,
                            value=customjson.dumps(balance.serialize(data=False, full=False))
                        )
                    await pipe.execute()

            await asyncio.sleep(0.5)
