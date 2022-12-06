import abc
import asyncio
from asyncio import Queue
from collections import deque
from typing import Dict, Optional, Deque, NamedTuple

from apscheduler.job import Job
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, and_, or_

from common.exchanges import EXCHANGES
from collector.services.baseservice import BaseService
from collector.services.dataservice import DataService, Channel, ExchangeInfo
from database.dbasync import db_all, db_unique, db_eager
from database.dbmodels import Balance
from database.dbmodels.client import Client, ClientState, ClientType
from database.dbmodels.editing import Journal
from database.dbmodels.trade import Trade
from database.errors import InvalidClientError
from common.exchanges.exchangeworker import ExchangeWorker
from common.messenger import CLIENT, TRADE, BALANCE
from common.messenger import TableNames, Category
from database.models.market import Market


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

    client_type: ClientType

    def __init__(self,
                 *args,
                 data_service: DataService,
                 **kwargs):
        super().__init__(*args, **kwargs)

        # Public parameters

        self.data_service = data_service
        self._exchanges = EXCHANGES
        self._workers_by_id: Dict[int, ExchangeWorker] = {}
        self._worker_lock = asyncio.Lock()
        self._updates = set()
        # self._worker_lock = Lock()

        self._all_client_stmt = db_eager(
            select(Client).where(
                ~Client.state.in_([ClientState.ARCHIVED, ClientState.INVALID])
            ),
            Client.currently_realized,
            (Client.open_trades, [Trade.max_pnl, Trade.min_pnl, Trade.init_balance]),
        )
        self._active_client_stmt = self._all_client_stmt.join(
            Trade,
            and_(
                Client.id == Trade.client_id,
                Trade.open_qty > 0
            )
        )

    @classmethod
    def is_valid(cls, worker: ExchangeWorker, category: ClientType):
        if category == ClientType.FULL and worker.supports_extended_data:
            return True
        elif category == ClientType.BASIC:
            return True

    async def _sub_client(self):
        async def _on_client_delete(data: Dict):
            await self._remove_worker_by_id(data['id'])
            await self._messenger.pub_channel(CLIENT,
                                              Category.REMOVED,
                                              data,
                                              client_id=data['id'])

        async def _on_client_update(data: dict):
            worker = self._get_existing_worker(data['id'])
            state = data['state']
            if worker:
                self._refresh_worker(worker)
                if state in ('archived', 'invalid') or data['type'] != self.client_type.value:
                    await self._remove_worker(worker)
            elif state != 'synchronizing' and data['type'] == self.client_type.value:
                await self.add_client_by_id(data['id'])

        def _on_client_add(data: Dict):
            if data['type'] == self.client_type.value:
                return self.add_client_by_id(data['id'])

        await self._messenger.bulk_sub(
            TableNames.CLIENT,
            {
                Category.NEW: _on_client_add,
                Category.UPDATE: _on_client_update,
                Category.DELETE: _on_client_delete,
            }
        )

    async def _refresh(self):
        available = set(self._updates)
        self._updates.clear()
        if available:
            return await db_all(
                self._all_client_stmt.where(
                    Client.id.in_(available)
                )
                .execution_options(populate_existing=True),
                session=self._db
            )
        return []

    async def _get_client(self, worker: ExchangeWorker):
        return await db_unique(
            self._all_client_stmt.where(
                Client.id == worker.client_id
            ).execution_options(populate_existing=True),
            session=self._db
        )

    def _refresh_worker(self, worker: ExchangeWorker):
        self._updates.add(worker.client_id)

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
        # async with self._db_maker() as db:
        #     client = await db.get(Client, client_id)
        if client:
            return await self.add_client(client)
        else:
            raise ValueError(f'Invalid {client_id=} passed in')

    async def add_client(self, client: Client) -> Optional[ExchangeWorker]:
        if client:
            exchange_cls = self._exchanges.get(client.exchange)
            if exchange_cls and issubclass(exchange_cls, ExchangeWorker):
                worker = exchange_cls(client,
                                      http_session=self._http_session,
                                      db_maker=self._db_maker,
                                      messenger=self._messenger)
                worker = await self._add_worker(worker)
                if worker:
                    await self._messenger.pub_instance(client, Category.ADDED)
                return worker
            else:
                self._logger.error(f'Exchange class {exchange_cls} does NOT subclass ExchangeWorker')

    async def teardown(self):
        async with self._worker_lock:
            for worker in self._workers_by_id.values():
                await worker.cleanup()
            self._workers_by_id = {}

    @abc.abstractmethod
    async def _remove_worker(self, worker: ExchangeWorker):
        pass

    @abc.abstractmethod
    async def _add_worker(self, worker: ExchangeWorker):
        pass


class BasicBalanceService(_BalanceServiceBase):
    client_type = ClientType.BASIC

    def __init__(self,
                 *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self._exchange_jobs: Dict[str, ExchangeJob] = {}
        self._balance_queue = Queue()

    @staticmethod
    def reschedule(exchange_job: ExchangeJob):
        trigger = IntervalTrigger(seconds=15 // (len(exchange_job.deque) or 1), jitter=2)
        exchange_job.job.reschedule(trigger)

    async def _add_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            if worker.client.id not in self._workers_by_id and self.is_valid(worker, ClientType.BASIC):
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
            await worker.cleanup()

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
                IntervalT rigger(seconds=3600),
                args=(exchange_queue,)
            )
            self._exchange_jobs[exchange] = ExchangeJob(exchange, job, exchange_queue)
        clients = await db_all(
                self._all_client_stmt.filter(
                    or_(
                        Client.type == ClientType.BASIC,
                        Client.exchange.in_([
                            ExchangeCls.exchange for ExchangeCls in self._exchanges.values()
                            if not ExchangeCls.supports_extended_data
                        ])
                    )
                ),
                session=self._db
        )
        for client in clients:
            try:
                await self.add_client(client)
            except Exception:
                # TODO: Schedule retry?
                continue

    async def run_forever(self):
        while True:
            # For efficiency reasons, balances are always grouped in 2-second intervals
            # (fewer round trips to database)
            balances = [await self._balance_queue.get()]

            await asyncio.sleep(2)
            while not self._balance_queue.empty():
                balances.append(self._balance_queue.get_nowait())

            self._db.add_all(balances)
            await self._db.commit()


class ExtendedBalanceService(_BalanceServiceBase):
    client_type = ClientType.FULL

    async def init(self):
        await self._sub_client()

        self._messenger.listen_class_all(Client)
        self._messenger.listen_class_all(Balance)
        self._messenger.listen_class_all(Trade)

        await self._messenger.bulk_sub(
            TRADE,
            {
                Category.UPDATE: self._on_trade_update,
                Category.NEW: self._on_trade_new,
                TRADE.FINISHED: self._on_trade_finished,
            }
        )
        clients = await db_all(
            self._all_client_stmt.filter(
                Client.type == ClientType.FULL,
                Client.exchange.in_([
                    ExchangeCls.exchange for ExchangeCls in self._exchanges.values()
                    if ExchangeCls.supports_extended_data
                ])
            ),
            session=self._db
        )
        for client in clients:
            try:
                await self.add_client(client)
            except Exception as e:
                self._logger.error('Could not add client')
        #
        return
        await asyncio.gather(
            *[
                self.add_client(client)
                for client in clients
            ],
            return_exceptions=True
        )
        pass

    async def _on_trade_new(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=True)
        if worker:
            self._refresh_worker(worker)
            await self.data_service.subscribe(
                worker.client.exchange_info,
                Channel.TICKER,
                symbol=data['symbol']
            )

    async def _on_trade_update(self, data: Dict):
        client_id = data['client_id']

        worker = await self.get_worker(client_id, create_if_missing=True)
        if worker:
            self._refresh_worker(worker)

    async def _on_trade_finished(self, data: Dict):
        worker = await self.get_worker(data['client_id'], create_if_missing=False)
        if worker:
            async with self._db_lock:
                client = await self._get_client(worker)
            if len(client.open_trades) == 0:
                symbol = data['symbol']
                # If there are no trades on the same exchange matching the deleted symbol,
                # there is no need to keep it subscribed
                unsubscribe_symbol = all(
                    trade.symbol != symbol
                    for cur_worker in self._workers_by_id.values()
                    if client.exchange == cur_worker.exchange
                    for trade in client.open_trades
                )
                if unsubscribe_symbol:
                    await self.data_service.unsubscribe(client.exchange_info, Channel.TICKER, symbol=symbol)
                await self._remove_worker(worker)

    async def _add_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            self._workers_by_id[worker.client.id] = worker

        if self.is_valid(worker, ClientType.FULL):
            try:
                await worker.synchronize_positions()
                await worker.startup()
                return worker
            except InvalidClientError:
                self._logger.exception(f'Error while adding {worker.client_id=}')

                return None
            except Exception:
                self._logger.exception(f'Error while adding {worker.client_id=}')
                raise

    async def _remove_worker(self, worker: ExchangeWorker):
        async with self._worker_lock:
            self._workers_by_id.pop(worker.client_id, None)
        await worker.cleanup()

    async def get_worker(self, client_id: int, create_if_missing=True) -> ExchangeWorker:
        async with self._worker_lock:
            if client_id:
                worker = self._workers_by_id.get(client_id)
                if not worker and create_if_missing:
                    worker = await self.add_client_by_id(client_id)
                return worker

    async def run_forever(self):
        while True:

            balances = []
            async with self._redis.pipeline(transaction=True) as pipe:

                async with self._worker_lock, self._db_lock:
                    await self._refresh()
                    for worker in self._workers_by_id.values():
                        client = self._db.identity_map.get(
                            self._db.identity_key(Client, worker.client_id)
                        )
                        if not client:
                            client = await self._get_client(worker)

                        if not client:
                            await self._messenger.pub_channel(
                                TableNames.CLIENT, Category.DELETE, obj={'id': worker.client_id}, id=worker.client_id
                            )
                            continue

                        if client.state == ClientState.SYNCHRONIZING:
                            continue

                        if client and client.open_trades:
                            for trade in client.open_trades:
                                ticker = await self.data_service.get_ticker(trade.symbol, client.exchange_info)
                                extra_ticker = ticker
                                try:
                                    market = worker.get_market(trade.symbol)
                                    if market.quote != client.currency:
                                        extra_ticker = await self.data_service.get_ticker(
                                            worker.get_symbol(
                                                Market(base=market.base, quote=client.currency)
                                            ),
                                            client.exchange_info
                                        )
                                except NotImplementedError:
                                    pass

                                if ticker and extra_ticker:
                                    trade.update_pnl(
                                        trade.calc_upnl(ticker.price),
                                        extra_currencies={client.currency: extra_ticker.price},
                                    )
                                    await trade.set_live_pnl(pipe)
                            balance = client.evaluate_balance()
                            if balance != client.live_balance:
                                balances.append(balance)
                            client.live_balance = balance

                    await self._db.commit()
                if balances:
                    self._logger.debug(balances)

                for balance in balances:
                    await balance.client.as_redis(pipe).set_balance(balance)

                await pipe.execute()

                for balance in balances:
                    await self._messenger.pub_instance(balance, Category.LIVE)

                await asyncio.sleep(.5)
