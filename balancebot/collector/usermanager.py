from __future__ import annotations
import asyncio
from sqlalchemy import select

import aiohttp
import logging
import math
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, TYPE_CHECKING, Type

import pytz
from sqlalchemy import asc, desc, DateTime, delete

import balancebot.api.database as db
import balancebot.api.dbmodels.event as db_event
from balancebot.api.database_async import async_session, db as aio_db, db_first, db_all, db_select

from balancebot.api.dbmodels.balance import Balance
import balancebot.api.dbmodels.client as db_client
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.api.dbmodels.execution import Execution
from balancebot.api.dbmodels.serializer import Serializer
from balancebot.api.dbmodels.trade import Trade, trade_from_execution
import balancebot.bot.config as config
from balancebot.common.enums import Priority
from balancebot.common.messenger import Messenger, Category, SubCategory
from balancebot.common.models.history import History
from balancebot.common.models.singleton import Singleton
import balancebot.exchangeworker as exchange_worker

if TYPE_CHECKING:
    from balancebot.exchangeworker import ExchangeWorker


def db_match_balance_currency(balance: Balance, currency: str):
    result = None

    if balance is None:
        return None

    result = None

    if balance.currency != currency:
        if balance.extra_currencies:
            result_currency = balance.extra_currencies.get(currency)
            if not result_currency:
                result_currency = balance.extra_currencies.get(config.CURRENCY_ALIASES.get(currency))
            if result_currency:
                result = Balance(
                    amount=result_currency,
                    currency=currency,
                    time=balance.time
                )
    else:
        result = balance

    return result


class UserManager(Singleton):

    def init(self,
             exchanges: dict = None,
             fetching_interval_hours: int = 4,
             rekt_threshold: float = 2.5,
             data_path: str = ''):

        # Public parameters
        self.interval_hours = fetching_interval_hours
        self.rekt_threshold = rekt_threshold
        self.data_path = data_path
        self.backup_path = self.data_path + 'backup/'

        self._exchanges = exchanges
        self._workers: List[ExchangeWorker] = []
        self._workers_by_client_id: Dict[int, ExchangeWorker] = {}

        self.session = aiohttp.ClientSession()
        self.messenger = Messenger()

        self.messenger.sub_channel(Category.CLIENT, sub=SubCategory.NEW, callback=self._on_client_delete)
        self.messenger.sub_channel(Category.CLIENT, sub=SubCategory.DELETE, callback=self._on_client_add)

    def get_workers(self):
        return self._workers

    def _on_client_delete(self, client_id: int):
        self._remove_worker(self._workers_by_client_id.get(client_id))

    def _on_client_add(self, client_id: int):
        self.add_client(db.session.query(db_client.Client).filter_by(id=client_id))

    def _add_worker(self, worker: ExchangeWorker):
        if worker not in self._workers:
            self._workers.append(worker)
            self._workers_by_client_id[worker.client.id] = worker

            def worker_callback(category, sub_category):
                async def callback(worker: ExchangeWorker, obj: Serializer):
                    self.messenger.pub_channel(category, sub=sub_category,
                                               channel_id=worker.client_id, obj=await obj.serialize())
                return callback

            worker.set_trade_update_callback(
                worker_callback(Category.TRADE, SubCategory.UPDATE)
            )
            worker.set_trade_callback(
                worker_callback(Category.TRADE, SubCategory.NEW)
            )
            worker.set_balance_callback(
                worker_callback(Category.BALANCE, SubCategory.NEW)
            )

    def _remove_worker(self, worker: ExchangeWorker):
        if worker in self._workers:
            self._workers_by_client_id.pop(worker.client.id, None)
            self._workers.remove(worker)
            del worker

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

    async def fetch_data(self, clients: List[db_client.Client] = None, guild_id: int = None):
        workers = [self.get_worker(client) for client in clients]
        return await self._async_fetch_data(workers)

    async def get_client_balance(self,
                                 client: db_client.Client,
                                 currency: str = None,
                                 priority: Priority = Priority.HIGH,
                                 force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = await self._async_fetch_data(workers=[self.get_worker(client)], keep_errors=True,
                                            priority=priority,
                                            force_fetch=force_fetch)

        if data:
            result = data[0]

            if result.error is None or result.error == '':
                matched_balance = db_match_balance_currency(result, currency)
                if matched_balance:
                    result = matched_balance
                else:
                    result.error = f'User balance does not contain currency {currency}'
        else:
            result = await client.latest()

        return result

    async def synch_workers(self):
        #clients = db.session.query(db_client.Client).all()
        clients = await db_all(
            select(db_client.Client),
            db_client.Client.events,
            (db_client.Client.discorduser, DiscordUser.global_associations)
        )

        for client in clients:
            if await client.is_global() or client.is_active:
                self.add_client(client)
            else:
                self._remove_worker(self.get_worker(client, create_if_missing=False))

    def add_client(self, client):
        client_cls = self._exchanges[client.exchange]
        if issubclass(client_cls, exchange_worker.ExchangeWorker):
            worker = client_cls(client, self.session)
            asyncio.create_task(worker.connect())
            self._add_worker(worker)
            return worker
        else:
            logging.error(f'CRITICAL: Exchange class {client_cls} does NOT subclass ClientWorker')

    def get_worker(self, client: db_client.Client, create_if_missing=True) -> ExchangeWorker:
        if client:
            worker = self._workers_by_client_id.get(client.id)
            if not worker and create_if_missing:
                self.add_client(client)
                worker = self._workers_by_client_id.get(client.id)
            return worker

    async def get_client_history(self,
                                 client: db_client.Client,
                                 event: db_event.Event,
                                 since: datetime = None,
                                 to: datetime = None,
                                 currency: str = None) -> History:

        since = since or datetime.fromtimestamp(0, tz=pytz.utc)
        to = to or datetime.now(pytz.utc)

        if event:
            # When custom times are given make sure they don't exceed event boundaries (clients which are global might have more data)
            since = max(since, event.start)
            to = min(to, event.end)

        if currency is None:
            currency = '$'

        results = []
        initial = None

        filter_time = event.start if event else since

        history = await db_all(client.history.statement.filter(
            Balance.time > filter_time, Balance.time < to
        ))

        first = await db_first(
            client.history.statement.filter(
                Balance.time > filter_time
            ).order_by(
                asc(Balance.time)
            )
        )

        latest = await client.latest()

        for balance in history:
            if since <= balance.time <= to:
                if currency != '$':
                    balance = db_match_balance_currency(balance, currency)
                if balance:
                    results.append(balance)
            elif event and event.start <= balance.time and not initial:
                initial = balance

        if results:
            results.insert(0, Balance(
                time=since,
                amount=results[0].amount,
                currency=results[0].currency
            ))

        if not initial:
            try:
                initial = results[0]
            except (ValueError, IndexError):
                pass

        return History(
            data=results,
            initial=initial
        )

    async def clear_client_data(self,
                                client: db_client.Client,
                                start: datetime = None,
                                end: datetime = None,
                                update_initial_balance=False):
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now(pytz.utc)

        await aio_db(delete(Balance).filter(
            Balance.client_id == client.id,
            Balance.time >= start,
            Balance.time <= end
        ))

        history_record = await db_first(client.history.statement)
        if not history_record and update_initial_balance:
            client.rekt_on = None
            asyncio.create_task(self.get_client_balance(client, force_fetch=True))

        await async_session.commit()

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
            workers = self._workers

        data = []
        tasks = []

        logging.info(f'Fetching data for {len(workers)} workers {keep_errors=}')
        for worker in workers:
            if not worker or not worker.in_position:
                continue
            tasks.append(
                asyncio.create_task(worker.get_balance(time=time, priority=priority, force=force_fetch))
            )
        results = await asyncio.gather(*tasks)

        tasks = []
        for result in results:
            if isinstance(result, Balance):
                client = await db_select(db_client.Client, id=result.client_id)
                if client:
                    tasks.append(
                        lambda: self.messenger.pub_channel(Category.BALANCE, SubCategory.NEW, channel_id=client.id,
                                                           obj=result.id)
                    )
                    history = await db_all(client.history.order_by(desc(Balance.time)).limit(3))
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
                        async_session.add(result)
                        data.append(result)
                        if result.amount <= self.rekt_threshold and not client.rekt_on:
                            client.rekt_on = time
                            self.messenger.pub_channel(Category.CLIENT, SubCategory.REKT, channel_id=client.id,
                                                       obj={'id': client.id})
                else:
                    logging.error(f'Worker with {result.client_id=} got no client object!')

        await async_session.commit()

        for task in tasks:
            task()

        logging.info(f'Done Fetching')
        return data
