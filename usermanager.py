import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from threading import RLock, Timer, Thread
from typing import List, Tuple, Dict, Callable, Optional, Any

from models.balance import Balance, balance_from_json
from models.trade import Trade
from models.discorduser import DiscordUser
from models.discorduser import user_from_json
from config import CURRENCY_ALIASES
from models.singleton import Singleton

import api.dbutils as dbutils
from api.database import db, Session
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.balance import Balance
from api.dbmodels.client import Client
from api.dbmodels.event import Event
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
        # Privates
        self._users = []
        self._users_by_id: Dict[int, Dict[int, DiscordUser]] = {}  # { user_id: { guild_id: User} }
        self._exchanges = exchanges

        self._user_data: List[Tuple[datetime, Dict[int, Dict[int, Balance]]]] = []
        self._user_trades: Dict[DiscordUser, List[Trade]] = {}
        self._workers: List[ClientWorker] = []
        self._worker_lock = RLock()

        self._user_lock = RLock()
        self._data_lock = RLock()

        self._last_full_fetch = {}
        self._saves_since_backup = 0
        self._load_user_data()

        # Set up paths and load data
        if not os.path.exists(self.backup_path):
            os.mkdir(self.backup_path)

        # if os.path.exists(self.data_path):
        #    self.load_registered_users()
        # else:
        #    os.mkdir(self.data_path)
        self._workers_by_id: Dict[Optional[int], Dict[int, ClientWorker]] = {}  # { event_id: { user_id: ClientWorker } }
        self._workers_by_client_id: Dict[int, ClientWorker] = {}

        self.synch_workers()

    def set_flask_app(self, app):
        self._app = app

    def load_registered_users(self):
        try:
            with open(self.data_path + 'users.json', 'r') as f:
                users_json = json.load(fp=f)
                for user_json in users_json:
                    try:
                        user = user_from_json(user_json, self._exchanges)
                        self.add_user(user)
                    except KeyError as e:
                        logging.error(f'{e} occurred while parsing user data {user_json} from users.json')
        except FileNotFoundError:
            logging.info(f'No user information found')
        except json.decoder.JSONDecodeError:
            pass

    def add_user(self, user: DiscordUser):
        with self._user_lock:
            if user not in self._users:
                if user.id not in self._users_by_id:
                    self._users_by_id[user.id] = {}
                self._users_by_id[user.id][user.guild_id] = user
                self._users.append(user)
                user.api.set_on_trade_callback(self._on_trade, user)

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
        self._remove_worker(self._get_worker(client))
        Client.query.filter_by(id=client.id).all().delete(synchronize_session=True)

    def get_users_by_id(self):
        with self._user_lock:
            return self._users_by_id.copy()

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

    def fetch_data(self, clients: List[Client] = None, guild_id: int = None, time_tolerance_seconds: float = 60):
        workers = [self._get_worker(client) for client in clients]
        self._db_fetch_data(workers, guild_id)

    def get_user_balance(self, user: DiscordUser, guild_id: int, currency: str = None, force_fetch=False) -> Balance:

        if currency is None:
            currency = '$'

        data = self._db_fetch_data(workers=[self._get_worker_event(user.user_id, guild_id)], keep_errors=True, force_fetch=force_fetch)

        result = data[0]

        if result.error is None or result.error == '':
            matched_balance = self.match_balance_currency(result, currency)
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
            matched_balance = self.match_balance_currency(result, currency)
            if matched_balance:
                result = matched_balance
            else:
                result.error = f'User balance does not contain currency {currency}'

        return result

    def synch_workers(self):
        clients = Client.query.all()

        for client in clients:
            if client.is_global or client.is_active:
                client_cls = self._exchanges[client.exchange]
                if issubclass(client_cls, ClientWorker):
                    worker = client_cls(client)
                    worker.set_on_trade_callback(self._on_trade)
                    self._add_worker(worker)
                else:
                    logging.error(f'CRITICAL: Exchange class {client_cls} does NOT subclass ClientWorker')
            else:
                worker = self._get_worker(client)
                if worker:
                    self._remove_worker(worker)

    def _get_worker(self, client: Client) -> ClientWorker:
        with self._worker_lock:
            return self._workers_by_client_id.get(client.id)

    def _get_worker_event(self, user_id, guild_id):
        with self._worker_lock:
            event = dbutils.get_event(guild_id)
            return self._workers_by_id[event.id if event else None].get(user_id)

    def get_balance_from_data(self, data, user_id: int, guild_id: int = None, exact=False) -> Optional[Balance]:
        balance = None

        if user_id in data:
            balance = data[user_id].get(guild_id, None)
            if not balance and not exact:
                balance = data[user_id].get(None, None)

        return balance

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
                    balance = self.match_balance_currency(balance, currency)
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
                            client.history.append(balance)
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

    def _save_user_data(self):

        try:
            if self._saves_since_backup >= self.interval_hours * 24:
                shutil.copy(self.data_path + 'user_data.json', self.backup_path + "backup_user_data.json")
                self._saves_since_backup = 0
            else:
                self._saves_since_backup += 1
        except FileNotFoundError as e:
            logging.error(f'{e} occurred while backing up user data.')

        self._data_lock.acquire()

        with open(self.data_path + "user_data.json", "w") as f:
            user_data_json = []
            prev_date, prev_data = datetime.fromtimestamp(0), {}
            for date, data in self._user_data:
                # Data is removed if
                # - it doesn't contain anything
                # - it isn't further than 10 minutes apart from the last timestamp and all common users have the same entries
                if len(data.keys()) == 0 or ((date - prev_date) < timedelta(minutes=10)
                                             and all(
                            data[key] == prev_data[key] for key in data.keys() & prev_data.keys())):
                    if len(data.keys()) < len(prev_data.keys()) or len(data.keys()) == 0:
                        self._user_data.remove((date, data))
                        date = prev_date
                        data = prev_data
                    elif (prev_date, prev_data) in self._user_data:
                        self._user_data.remove((prev_date, prev_data))
                else:
                    user_data_json.append(
                        (round(date.timestamp()),
                         {user_id: {guild_id: data[user_id][guild_id].to_json() for guild_id in data[user_id]} for
                          user_id in data})
                    )
                prev_date = date
                prev_data = data

            json.dump(fp=f, obj=user_data_json)

        self._data_lock.release()

    def _load_user_data(self):

        raw_json_merge = None
        try:
            with open(self.data_path + "user_data_merge.json", "r") as f:
                raw_json_merge = json.load(fp=f)
        except FileNotFoundError:
            logging.info('No user data for merging found')
        except json.JSONDecodeError as e:
            logging.error(f'{e}: Error while parsing merge user data.')

        try:
            with open(self.data_path + "user_data.json", "r") as f:
                raw_json = json.load(fp=f)
                if raw_json:
                    if raw_json_merge:
                        # This is a mess and kind of unnecessary...
                        index_normal = 0
                        index_merge = 0
                        len_normal = len(raw_json)
                        len_merge = len(raw_json_merge)
                        while index_merge < len_merge or index_normal < len_normal:
                            if index_normal < len_normal:
                                ts_normal, data_normal = raw_json[index_normal]
                            if index_merge < len_merge:
                                ts_merge, data_merge = raw_json_merge[index_merge]
                            if ts_normal < ts_merge or index_merge == len_merge:
                                self._append_from_json(ts_normal, data_normal)
                                index_normal += 1 if index_normal < len_normal else 0
                            elif ts_merge < ts_normal or index_normal == len_normal:
                                self._append_from_json(ts_merge, data_merge)
                                index_merge += 1 if index_merge < len_merge else 0
                            else:
                                for merge in data_merge:
                                    if merge not in data_normal:
                                        data_normal[merge] = data_merge[merge]
                                self._append_from_json(ts_normal, data_normal)
                                index_normal += 1 if index_normal < len_normal else 0
                                index_merge += 1 if index_merge < len_merge else 0
                    else:
                        for ts, data in raw_json:
                            self._append_from_json(ts, data)
        except FileNotFoundError:
            logging.info('No user data found')
        except json.JSONDecodeError as e:
            logging.error(f'{e}: Error while parsing user data.')

    def _on_trade(self, client_id: int, trade: Trade):
        client = Client.query.filter_by(id=client_id).first()
        client.trades.append(trade)
        db.session.commit()
        logging.info('Got new Trade')

    def _append_from_json(self, ts: int, user_json: dict):
        user_data = {}

        for user_id in user_json:
            user_balances = {}
            for key in user_json[user_id].keys():
                if key != 'extra_currencies' and isinstance(user_json[user_id][key], dict):  # Backwards compatibility
                    user_balances[None if key == 'null' else int(key)] = balance_from_json(user_json[user_id][key])
            if len(user_balances) == 0:
                user_balances[None] = balance_from_json(user_json[user_id])
            user_data[int(user_id)] = user_balances

        self._data_lock.acquire()
        self._user_data.append((datetime.fromtimestamp(ts), user_data))
        self._data_lock.release()

    def match_balance_currency(self, balance: Balance, currency: str):
        result = None

        if balance is None:
            return None

        if balance.currency != currency:
            if balance.extra_currencies:
                result_currency = balance.extra_currencies.get(currency)
                if not result_currency:
                    result_currency = balance.extra_currencies.get(CURRENCY_ALIASES.get(currency))
                if result_currency:
                    result = Balance(amount=result_currency, currency=currency)
        else:
            result = balance

        return result

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
