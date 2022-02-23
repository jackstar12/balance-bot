import json
import logging
import math
import os
import shutil
from datetime import datetime, timedelta
from threading import RLock, Timer, Thread
from typing import List, Tuple, Dict, Callable, Optional, Any

from api.dbmodels.trade import Trade, trade_from_execution
from models.singleton import Singleton
from config import CURRENCY_ALIASES

import api.dbutils as dbutils
from api.database import db
from api.dbmodels.discorduser import DiscordUser, add_user_from_json
from api.dbmodels.balance import Balance, balance_from_json
from api.dbmodels.client import Client
from api.dbmodels.execution import Execution
from clientworker import ClientWorker


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

        self._db = db
        self._db_lock = RLock()
        self._exchanges = exchanges

        self._workers: List[ClientWorker] = []
        self._worker_lock = RLock()

        self._user_lock = RLock()
        self._data_lock = RLock()

        self._last_full_fetch = {}
        self._saves_since_backup = 0

        self._workers_by_id: Dict[
            Optional[int], Dict[int, ClientWorker]] = {}  # { event_id: { user_id: ClientWorker } }
        self._workers_by_client_id: Dict[int, ClientWorker] = {}

        self.synch_workers()

    def set_flask_app(self, app):
        self._app = app

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

    def remove_client(self, client: Client):
        self._remove_worker(self._get_worker(client, create_if_missing=False))
        Client.query.filter_by(id=client.id).delete()
        db.session.commit()

    def start_fetching(self):
        """
        Start fetching data at specified interval
        """

        self._db_fetch_data(set_full_fetch=True)

        time = datetime.now()
        next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                            microsecond=0) + timedelta(hours=self.interval_hours)
        delay = next - time

        timer = Timer(delay.total_seconds(), self.start_fetching)
        timer.daemon = True
        timer.start()

    def fetch_data(self, clients: List[Client] = None, guild_id: int = None):
        workers = [self._get_worker(client) for client in clients]
        self._db_fetch_data(workers, guild_id)

    def get_user_balance(self, user: DiscordUser, guild_id: int, currency: str = None, force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = self._db_fetch_data(workers=[self._get_worker_event(user.user_id, guild_id)], keep_errors=True,
                                   force_fetch=force_fetch)

        result = data[0]

        if result.error is None or result.error == '':
            matched_balance = self.db_match_balance_currency(result, currency)
            if matched_balance:
                result = matched_balance
            else:
                result.error = f'User balance does not contain currency {currency}'

        return result

    def get_client_balance(self, client: Client, currency: str = None, force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = self._db_fetch_data(workers=[self._get_worker(client)], keep_errors=True, force_fetch=force_fetch)

        result = data[0]

        if result.error is None or result.error == '':
            matched_balance = self.db_match_balance_currency(result, currency)
            if matched_balance:
                result = matched_balance
            else:
                result.error = f'User balance does not contain currency {currency}'

        return result

    def synch_workers(self):
        clients = Client.query.all()

        for client in clients:
            if client.is_global or client.is_active:
                self.add_client(client)
            else:
                self._remove_worker(self._get_worker(client, create_if_missing=False))

    def add_client(self, client):
        client_cls = self._exchanges[client.exchange]
        if issubclass(client_cls, ClientWorker):
            worker = client_cls(client)
            worker.set_execution_callback(self._on_execution)
            self._add_worker(worker)
        else:
            logging.error(f'CRITICAL: Exchange class {client_cls} does NOT subclass ClientWorker')

    def _get_worker(self, client: Client, create_if_missing=True) -> ClientWorker:
        with self._worker_lock:
            worker = self._workers_by_client_id.get(client.id)
            if not worker and create_if_missing:
                self.add_client(client)
                worker = self._workers_by_client_id.get(client.id)
            return worker

    def _get_worker_event(self, user_id, guild_id):
        with self._worker_lock:
            event = dbutils.get_event(guild_id)
            return self._workers_by_id[event.id if event else None].get(user_id)

    def get_client_history(self,
                           client: Client,
                           guild_id: int,
                           start: datetime = None,
                           end: datetime = None,
                           currency: str = None) -> List[Balance]:

        start, end = dbutils.get_guild_start_end_times(guild_id, start, end)
        if currency is None:
            currency = '$'

        results = []

        for balance in client.history:
            if start <= balance.time <= end:
                if currency != '$':
                    balance = self.db_match_balance_currency(balance, currency)
                if balance:
                    results.append(balance)

        return results

    def clear_client_data(self,
                          client: Client,
                          start: datetime = None,
                          end: datetime = None,
                          update_initial_balance=False):
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()

        for balance in client.history:
            if start <= balance.time <= end:
                client.history.remove(balance)

        if len(client.history) > 0 and update_initial_balance:
            self.get_client_balance(client)

        db.session.commit()

    def _db_fetch_data(self, workers: List[ClientWorker] = None, guild_id: int = None, keep_errors: bool = False,
                       set_full_fetch=False, force_fetch=False) -> List[Balance]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to guild entries with Balance objects (non-errors only)
        """
        time = datetime.now()

        if set_full_fetch:
            self._last_full_fetch[guild_id] = time

        with self._worker_lock:
            if workers is None:
                workers = self._workers

            data = []
            logging.info(f'Fetching data for {len(workers)} users {keep_errors=}')
            for worker in workers:
                if not worker:
                    continue
                client = Client.query.filter_by(id=worker.client_id).first()
                # TODO: Think about non event members
                if client.rekt_on and not force_fetch:
                    balance = Balance(0.0, '$', None)
                else:
                    balance = worker.get_balance(time)
                if balance:
                    if balance.error:
                        logging.error(f'Error while fetching user {worker} balance: {balance.error}')
                        if keep_errors:
                            data.append(balance)
                    else:
                        client.history.append(balance)
                        data.append(balance)
                        if balance.amount <= self.rekt_threshold and not client.rekt_on:
                            client.rekt_on = time
                            if callable(self.on_rekt_callback):
                                self.on_rekt_callback(worker)
                else:
                    data.append(client.history[len(client.history) - 1])
            db.session.commit()

        logging.info(f'Done Fetching')
        return data

    def _on_execution(self, client_id: int, execution: Execution):

        active_trade = Trade.query.filter(
            Trade.symbol == execution.symbol,
            Trade.client_id == client_id,
            Trade.open_qty > 0.0
        ).first()

        def weighted_avg(values: Tuple[float, float], weights: Tuple[float, float]):
            total = weights[0] + weights[1]
            return values[0] * (weights[0] / total) + values[1] * (weights[1] / total)

        if active_trade:
            active_trade.executions.append(execution)
            if execution.side == active_trade.initial.side:
                active_trade.entry = weighted_avg((active_trade.entry, execution.price),
                                                  (active_trade.qty, execution.qty))
                active_trade.qty += execution.qty
                active_trade.open_qty += execution.qty
            else:
                if execution.qty > active_trade.open_qty:
                    new_execution = Execution(
                        qty=execution.qty - active_trade.open_qty,
                        symbol=execution.symbol,
                        price=execution.price,
                        side=execution.side,
                        time=execution.time
                    )
                    execution.qty = active_trade.qty
                    new_trade = trade_from_execution(new_execution)
                    client = Client.query.filter_by(id=client_id).first()
                    client.trades.append(new_trade)
                if execution.qty <= active_trade.qty:
                    if active_trade.exit is None:
                        active_trade.exit = execution.price
                    else:
                        active_trade.exit = weighted_avg((active_trade.exit, execution.price),
                                                         (active_trade.open_qty, execution.qty))
                    if math.isclose(active_trade.open_qty, execution.qty, rel_tol=10e-6):
                        active_trade.open_qty = 0.0
                    else:
                        active_trade.open_qty -= execution.qty
                    realized_qty = active_trade.qty - active_trade.open_qty
                    active_trade.realized_pnl = active_trade.exit * realized_qty - active_trade.entry * realized_qty * (1 if active_trade.initial.side == 'BUY' else -1)
        else:
            trade = trade_from_execution(execution)
            client = Client.query.filter_by(id=client_id).first()
            client.trades.append(trade)
        db.session.commit()

    def db_match_balance_currency(self, balance: Balance, currency: str):
        result = None

        if balance is None:
            return None

        if balance.currency != currency:
            if balance.extra_currencies:
                result_currency = balance.extra_currencies.get(currency)
                if not result_currency:
                    result_currency = balance.extra_currencies.get(CURRENCY_ALIASES.get(currency))
                if result_currency:
                    result.amount = result_currency
                    result.currency = currency
        else:
            result = balance

        return result
