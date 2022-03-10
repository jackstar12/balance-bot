import json
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
from clientworker import ClientWorker
from config import CURRENCY_ALIASES
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

        self._db = db
        self._db_lock = RLock()
        self._exchanges = exchanges

        self._workers: List[ClientWorker] = []
        self._worker_lock = RLock()

        self._user_lock = RLock()
        self._data_lock = RLock()

        self._last_full_fetch = {}
        self._saves_since_backup = 0

        self._workers_by_id: Dict[Optional[int], Dict[int, ClientWorker]] = {}  # { event_id: { user_id: ClientWorker } }
        self._workers_by_client_id: Dict[int, ClientWorker] = {}

        self.synch_workers()

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

    def delete_client(self, client: Client, commit=True):
        self._remove_worker(self._get_worker(client, create_if_missing=False))
        Client.query.filter_by(id=client.id).delete()
        if commit:
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

    def get_client_balance(self, client: Client, currency: str = None, force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = self._db_fetch_data(workers=[self._get_worker(client)], keep_errors=True, force_fetch=force_fetch)

        result = None
        if data:
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
            return self._workers_by_id[event].get(user_id)

    def get_client_history(self,
                           client: Client,
                           guild_id: int,
                           start: datetime = None,
                           end: datetime = None,
                           currency: str = None,
                           archived = False) -> List[Balance]:

        start, end = dbutils.get_guild_start_end_times(guild_id, start, end, archived=archived)
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

        Balance.query.filter(
            Balance.client_id == client.id,
            Balance.time >= start,
            Balance.time <= end
        ).delete()

        db.session.commit()

        if len(client.history) == 0 and update_initial_balance:
            self.get_client_balance(client, force_fetch=True)

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
            logging.info(f'Fetching data for {len(workers)} workers {keep_errors=}')
            for worker in workers:
                if not worker:
                    continue
                client = Client.query.filter_by(id=worker.client_id).first()
                if client:
                    if client.rekt_on and not force_fetch:
                        balance = Balance(amount=0.0, currency='$', extra_currencies={}, error=None, time=time)
                    else:
                        balance = worker.get_balance(time, force=force_fetch)
                    latest_balance = None if len(client.history) == 0 else client.history[len(client.history) - 1]
                    if balance:
                        # If balance hasn't changed at all, why bother keeping it?
                        if latest_balance and not math.isclose(latest_balance.amount, balance.amount, rel_tol=1e-06):
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
                            latest_balance.time = time
                            data.append(latest_balance)
                    elif latest_balance:
                        data.append(latest_balance)
                else:
                    logging.error(f'Worker with {worker.client_id=} got no client object!')
            db.session.commit()

        logging.info(f'Done Fetching')
        return data

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
