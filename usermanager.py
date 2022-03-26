from __future__ import annotations
import json
import asyncio
import aiohttp
import logging
import math
from datetime import datetime, timedelta
from threading import RLock, Timer
from typing import List, Dict, Callable, Optional, Any

import api.dbutils as dbutils
from api.database import db
from api.dbmodels.balance import Balance
from api.dbmodels.client import Client
from api.dbmodels.discorduser import DiscordUser
import api.dbmodels.event as db_event
from clientworker import ClientWorker
from config import CURRENCY_ALIASES
from models.history import History
from models.singleton import Singleton


class UserManager(Singleton):

    def init(self,
             exchanges: dict = None,
             fetching_interval_hours: int = 4,
             rekt_threshold: float = 2.5,
             data_path: str = '',
             on_rekt_callback: Callable[[DiscordUser], Any] = None):

        # Public parameters
        self.interval_hours = fetching_interval_hours
        self.rekt_threshold = rekt_threshold
        self.data_path = data_path
        self.backup_path = self.data_path + 'backup/'
        self.on_rekt_callback = on_rekt_callback

        self._exchanges = exchanges
        self._worker_lock = RLock()
        self._workers: List[ClientWorker] = []
        self._workers_by_id: Dict[
            Optional[int], Dict[int, ClientWorker]] = {}  # { event_id: { user_id: ClientWorker } }
        self._workers_by_client_id: Dict[int, ClientWorker] = {}

        self.session = aiohttp.ClientSession()

    def _add_worker(self, worker: ClientWorker):
        with self._worker_lock:
            if worker not in self._workers:
                self._workers.append(worker)
                for event in [None, *worker.client.events]:
                    if event not in self._workers_by_id:
                        self._workers_by_id[event] = {}
                    self._workers_by_id[event][worker.client.discorduser.id] = worker
                self._workers_by_client_id[worker.client.id] = worker

    def _remove_worker(self, worker: ClientWorker):
        with self._worker_lock:
            if worker in self._workers:
                for event in [None, *worker.client.events]:
                    self._workers_by_id[event].pop(worker.client.discorduser.id)
                self._workers_by_client_id.pop(worker.client.id)
                self._workers.remove(worker)
                del worker

    def delete_client(self, client: api_client.Client, commit=True):
        self._remove_worker(self._get_worker(client, create_if_missing=False))
        api_client.Client.query.filter_by(id=client.id).delete()
        if commit:
            db.session.commit()

    async def start_fetching(self):
        """
        Start fetching data at specified interval
        """
        while True:
            await self._async_fetch_data()
            time = datetime.now()
            next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                                microsecond=0) + timedelta(hours=self.interval_hours)
            delay = next - time
            await asyncio.sleep(delay.total_seconds())

    async def fetch_data(self, clients: List[api_client.Client] = None, guild_id: int = None):
        workers = [self._get_worker(client) for client in clients]
        return await self._async_fetch_data(workers)

    async def get_client_balance(self, client:api_client. Client, currency: str = None, force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = await self._async_fetch_data(workers=[self._get_worker(client)], keep_errors=True, force_fetch=force_fetch)

        if data:
            result = data[0]

            if result.error is None or result.error == '':
                matched_balance = self.db_match_balance_currency(result, currency)
                if matched_balance:
                    result = matched_balance
                else:
                    result.error = f'User balance does not contain currency {currency}'
        else:
            result = client.latest

        return result

    def synch_workers(self):
        clients = api_client.Client.query.all()

        for client in clients:
            if client.is_global or client.is_active:
                self.add_client(client)
            else:
                self._remove_worker(self._get_worker(client, create_if_missing=False))

    def add_client(self, client):
        client_cls = self._exchanges[client.exchange]
        if issubclass(client_cls, ClientWorker):
            worker = client_cls(client, self.session)
            worker.set_execution_callback(self._on_execution)
            self._add_worker(worker)
        else:
            logging.error(f'CRITICAL: Exchange class {client_cls} does NOT subclass ClientWorker')

    def _get_worker(self, client: api_client.Client, create_if_missing=True) -> ClientWorker:
        with self._worker_lock:
            if client:
                worker = self._workers_by_client_id.get(client.id)
                if not worker and create_if_missing:
                    self.add_client(client)
                    worker = self._workers_by_client_id.get(client.id)
                return worker

    def _get_worker_event(self, user_id, guild_id):
        with self._worker_lock:
            event = dbutils.get_event(guild_id)
            return self._workers_by_id[event].get(user_id)

    def get_client_history(self,
                           client: api_client.Client,
                           event: db_event.Event,
                           since: datetime = None,
                           to: datetime = None,
                           currency: str = None,
                           archived=False) -> History:

        since = since or datetime.fromtimestamp(0)
        to = to or datetime.now()

        if event:
            # When custom times are given make sure they don't exceed event boundaries (clients which are global might have more data)
            since = max(since, event.start)
            to = min(to, event.end)

        if currency is None:
            currency = '$'

        results = []
        initial = None

        if event:
            for balance in client.history:
                if since <= balance.time <= to:
                    if currency != '$':
                        balance = self.db_match_balance_currency(balance, currency)
                    if balance:
                        results.append(balance)
                elif event.start <= balance.time and not initial:
                    initial = balance
        else:
            results = client.history

        if not initial:
            try:
                initial = results[0]
            except ValueError:
                pass

        return History(
            data=results,
            initial=initial
        )

    def clear_client_data(self,
                          client: api_client.Client,
                          start: datetime = None,
                          end: datetime = None,
                          update_initial_balance=False):
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()

        Balance.query.filter(
            Balance.client_id == client.id,
            Balance.time >= start,
            Balance.time <= end
        ).delete()

        db.session.commit()

        if len(client.history) == 0 and update_initial_balance:
            asyncio.create_task(self.get_client_balance(client, force_fetch=True))

    async def _async_fetch_data(self, workers: List[ClientWorker] = None,
                                keep_errors: bool = False,
                                force_fetch=False) -> List[Balance]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to guild entries with Balance objects (non-errors only)
        """
        time = datetime.now()

        if workers is None:
            workers = self._workers

        data = []
        tasks = []

        logging.info(f'Fetching data for {len(workers)} workers {keep_errors=}')
        for worker in workers:
            if not worker or not worker.in_position:
                continue
            tasks.append(
                asyncio.create_task(worker.get_balance(self.session, time, force=force_fetch))
            )
        results = await asyncio.gather(*tasks)

        for result in results:
            if isinstance(result, Balance):
                client = api_client.Client.query.filter_by(id=result.client_id).first()
                if client:
                    history_len = len(client.history)
                    latest_balance = None if history_len == 0 else client.history[history_len - 1]
                    if history_len > 2:
                        # If balance hasn't changed at all, why bother keeping it?
                        if math.isclose(latest_balance.amount, result.amount, rel_tol=1e-06) \
                                and math.isclose(client.history[history_len - 2].amount, result.amount, rel_tol=1e-06):
                            latest_balance.time = time
                            data.append(latest_balance)
                            continue
                    if result.error:
                        logging.error(f'Error while fetching {client.id=} balance: {result.error}')
                        if keep_errors:
                            data.append(result)

                    else:
                        client.history.append(result)
                        data.append(result)
                        if result.amount <= self.rekt_threshold and not client.rekt_on:
                            client.rekt_on = time
                            if callable(self.on_rekt_callback):
                                self.on_rekt_callback(client)
                else:
                    logging.error(f'Worker with {result.client_id=} got no client object!')

        db.session.commit()

        logging.info(f'Done Fetching')
        return data

    def _on_execution(self, client_id: int, execution: Execution):

        active_trade: Trade = Trade.query.filter(
            Trade.symbol == execution.symbol,
            Trade.client_id == client_id,
            Trade.open_qty > 0.0
        ).first()

        client: api_client.Client = api_client.Client.query.filter_by(id=client_id).first()
        worker = self._get_worker(client)

        if worker:
            worker.in_position = True
        else:
            logging.critical(f'on_execution callback: {active_trade.client=} for trade {active_trade} got no worker???')

        def weighted_avg(values: Tuple[float, float], weights: Tuple[float, float]):
            total = weights[0] + weights[1]
            return round(values[0] * (weights[0] / total) + values[1] * (weights[1] / total), ndigits=3)

        if active_trade:
            active_trade.executions.append(execution)

            if execution.side == active_trade.initial.side:
                active_trade.entry = weighted_avg((active_trade.entry, execution.price),
                                                  (active_trade.qty, execution.qty))
                active_trade.qty += execution.qty
                active_trade.open_qty += execution.qty
            else:
                new_execution = None
                if execution.qty > active_trade.open_qty:
                    new_execution = Execution(
                        qty=execution.qty - active_trade.open_qty,
                        symbol=execution.symbol,
                        price=execution.price,
                        side=execution.side,
                        time=execution.time
                    )
                    execution.qty = active_trade.open_qty
                    new_trade = trade_from_execution(new_execution)
                    client.trades.append(new_trade)
                    asyncio.create_task(self._async_fetch_data([worker]))
                if execution.qty <= active_trade.qty:
                    if active_trade.exit is None:
                        active_trade.exit = execution.price
                    else:
                        active_trade.exit = weighted_avg((active_trade.exit, execution.price),
                                                         (active_trade.open_qty, execution.qty))

                    if math.isclose(active_trade.open_qty, execution.qty, rel_tol=10e-6):
                        active_trade.open_qty = 0.0
                        asyncio.create_task(self._async_fetch_data([worker]))
                        if worker and not new_execution:
                            worker.in_position = False
                    else:
                        active_trade.open_qty -= execution.qty
                    realized_qty = active_trade.qty - active_trade.open_qty

                    active_trade.realized_pnl = (active_trade.exit * realized_qty - active_trade.entry * realized_qty) * (1 if active_trade.initial.side == 'BUY' else -1)
        else:
            trade = trade_from_execution(execution)
            client.trades.append(trade)
            asyncio.create_task(self._async_fetch_data([worker]))

        db.session.commit()

    def db_match_balance_currency(self, balance: Balance, currency: str):
        result = None

        if balance is None:
            return None

        result = None

        if balance.currency != currency:
            if balance.extra_currencies:
                result_currency = balance.extra_currencies.get(currency)
                if not result_currency:
                    result_currency = balance.extra_currencies.get(CURRENCY_ALIASES.get(currency))
                if result_currency:
                    result = Balance(
                        amount=result_currency,
                        currency=currency,
                        time=balance.time
                    )
        else:
            result = balance

        return result
