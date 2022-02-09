import json
import logging
import os
import shutil
from datetime import datetime, timedelta
from threading import Lock, Timer
from typing import List, Tuple, Dict, Callable, Optional, Any
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import extract, and_

from models.balance import Balance, balance_from_json
from models.trade import Trade
from models.discorduser import DiscordUser
from models.discorduser import user_from_json
from config import CURRENCY_ALIASES
from models.singleton import Singleton
from api.database import db
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
        # Privates
        self._users = []
        self._users_by_id: Dict[int, Dict[int, DiscordUser]] = {}  # { user_id: { guild_id: User} }
        self._exchanges = exchanges

        self._user_data: List[Tuple[datetime, Dict[int, Dict[int, Balance]]]] = []
        self._user_trades: Dict[DiscordUser, List[Trade]] = {}
        self._workers: List[ClientWorker] = []
        self._worker_lock = Lock()

        self._user_lock = Lock()
        self._data_lock = Lock()

        self._last_full_fetch = {}
        self._saves_since_backup = 0
        self._load_user_data()

        # Set up paths and load data
        if not os.path.exists(self.backup_path):
            os.mkdir(self.backup_path)

        #if os.path.exists(self.data_path):
        #    self.load_registered_users()
        #else:
        #    os.mkdir(self.data_path)
        self._workers_by_id: Dict[int, ClientWorker] = {}  # { user_id: ClientWorker }
        users = DiscordUser.query.all()
        for user in users:
            client_cls = exchanges[user.client.exchange]
            if issubclass(client_cls, ClientWorker):
                worker = client_cls(user.client)
                worker.on_trade(self._on_trade)
                self.db_add_worker(worker)
            else:
                logging.error(f'CRITICAL: Exchange class {client_cls} does NOT subclass ClientWorker')

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

    def save_registered_users(self):
        with open(self.data_path + 'users.json', 'w') as f:
            with self._user_lock:
                users_json = [user.to_json() for user in self._users]
                json.dump(obj=users_json, fp=f, indent=3)

    def add_user(self, user: DiscordUser):
        with self._user_lock:
            if user not in self._users:
                if user.id not in self._users_by_id:
                    self._users_by_id[user.id] = {}
                self._users_by_id[user.id][user.guild_id] = user
                self._users.append(user)
                user.api.on_trade(self._on_trade, user)

    def db_add_worker(self, worker: ClientWorker):
        with self._worker_lock:
            if worker not in self._workers:
                self._workers.append(worker)
                self._workers_by_id[worker.client.discorduser.user_id] = worker

    def remove_user(self, user: DiscordUser):
        with self._user_lock:
            self._users_by_id[user.id].pop(user.guild_id)

            if len(self._users_by_id[user.id]) == 0:
                self._users_by_id.pop(user.id)

            if user in self._users:
                self._users.remove(user)

    def get_users_by_id(self):
        with self._user_lock:
            return self._users_by_id.copy()

    def get_client(self,
                   user_id: int,
                   guild_id: int = None,
                   throw_exceptions=True):
        user = DiscordUser.query.filer_by(user_id=user_id)
        if user:
            if guild_id:
                event = Event.query.filter_by(guild_id=guild_id).first()
                if event:
                    for client in event.registrations:
                        if client.discorduser.user_id == user_id:
                            return client
                    raise ValueError("User {name} is not registered for this event")
            if user.global_client_id:
                return Client.query.filter_by(id=user.global_client_id).first()
            else:
                raise ValueError("User {name} does not have a global registration")
                pass # TODO: Adapt error fallback

    def get_user(self,
                 user_id: int,
                 guild_id: int = None,
                 exact: bool = False,
                 throw_exceptions=True) -> DiscordUser:
        """
        Tries to find a matching entry for the user and guild id.
        :param user_id: id of user to get
        :param guild_id: guild id of user to get
        :param throw_exceptions: whether to throw exceptions if user isn't registered
        :param exact: whether the global entry should be used if the guild isn't registered
        :return:
        The found user. It will never return None if throw_exceptions is True, since an ValueError exception will be thrown instead.
        """
        result = DiscordUser.query.filter_by(user_id=user_id)
        if not result and throw_exceptions:
            raise ValueError("User {name} does not have a global registration")
        return result

    def get_user_data(self):
        with self._data_lock:
            return self._user_data.copy()


    def start_fetching(self):
        """
                Start fetching data at specified interval
                """

        with self._data_lock:
            self._user_data.append(self._fetch_data(set_full_fetch=True))

        self._save_user_data()

        time = datetime.now()
        next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                            microsecond=0) + timedelta(hours=self.interval_hours)
        delay = next - time

        timer = Timer(delay.total_seconds(), self.start_fetching)
        timer.daemon = True
        timer.start()

    def fetch_data(self, users: List[DiscordUser] = None, guild_id: int = None, time_tolerance_seconds: float = 60):
        with self._data_lock:
            time, data = self._user_data[len(self._user_data) - 1]
            if not self._fetched_recently(guild_id, time_tolerance_seconds):
                time, data = self._fetch_data(users=users, guild_id=guild_id, set_full_fetch=True)
                self._user_data.append((time, data))
        return time, data

    def get_user_balance(self, user: DiscordUser, currency: str = None, force_fetch = False) -> Balance:

        if currency is None:
            currency = '$'

        data = self._db_fetch_data(workers=[self._get_worker(user.user_id)], keep_errors=True, force_fetch=force_fetch)

        result = data[0]

        if result.error is None or result.error == '':
            matched_balance = self.match_balance_currency(result, currency)
            if matched_balance:
                result = matched_balance
            else:
                result.error = f'User balance does not contain currency {currency}'

        return result

    def _get_worker(self, user_id: int) -> ClientWorker:
        with self._worker_lock:
            return self._workers_by_id.get(user_id)

    def get_balance_from_data(self, data, user_id: int, guild_id: int = None, exact=False) -> Optional[Balance]:
        balance = None

        if user_id in data:
            balance = data[user_id].get(guild_id, None)
            if not balance and not exact:
                balance = data[user_id].get(None, None)

        return balance

    def get_single_user_data(self,
                             user_id: int,
                             guild_id: int = None,
                             start: datetime = None,
                             end: datetime = None,
                             currency: str = None) -> List[Balance]:

        # Defaults.
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()
        if currency is None:
            currency = '$'

        user = self.get_user(user_id)
        results = Balance.query.filter(
            Balance.client_id == user.client.id, Balance.time > start, Balance.time < end
        ).all()

        if currency != '$':
            for result in results:
                result = self.match_balance_currency(result, currency)
                if result is None:
                    results.remove(result)

        return results

    def clear_user_data(self,
                        user: DiscordUser,
                        start: datetime = None,
                        end: datetime = None,
                        remove_all_guilds = False,
                        update_initial_balance = False):

        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()

        new_initial = None

        if len(self._user_data) == 0:
            return

        if start > self._user_data[0][0]:
            update_initial_balance = False

        with self._data_lock:
            for time, data in self._user_data:
                if user.id in data:
                    if start <= time <= end:
                        if remove_all_guilds:
                            data.pop(user.id)
                        elif user.guild_id in data[user.id]:
                            data[user.id].pop(user.guild_id)

        if update_initial_balance:
            new_initial = None
            with self._data_lock:
                self._data_lock.acquire()
                for time, data in self._user_data:
                    new_initial = self.get_balance_from_data(data, user.id, user.guild_id, exact=True)
                    if new_initial:
                        user.initial_balance = time, new_initial
                        break
            if not new_initial:
                user.initial_balance = datetime.now(), self.get_user_balance(user, force_fetch=True)

        self._save_user_data()

    def _fetched_recently(self, guild_id: int = None, time_tolerance_seconds: float = 60):
        last_fetch = self._last_full_fetch.get(guild_id)
        if not last_fetch:
            last_fetch = self._last_full_fetch.get(None)
        return datetime.now() - last_fetch < timedelta(seconds=time_tolerance_seconds)

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
                # TODO: Think about non event members
                if worker.client.rekt_on and not force_fetch:
                    balance = Balance(0.0, '$', None)
                else:
                    balance = worker.get_balance(time)
                if balance.error:
                    logging.error(f'Error while fetching user {worker} balance: {balance.error}')
                    if keep_errors:
                        data.append(balance)
                        worker.client.history.append(balance)
                else:
                    worker.client.history.append(balance)
                    data.append(balance)
                    if balance.amount <= self.rekt_threshold and not worker.client.rekt_on:
                        worker.client.rekt_on = time
                        if callable(self.on_rekt_callback):
                            self.on_rekt_callback(worker)
            db.session.commit()

        logging.info(f'Done Fetching')
        return data

    def _fetch_data(self, users: List[DiscordUser] = None, guild_id: int = None, keep_errors: bool = False, set_full_fetch = False, force_fetch = False) -> Tuple[datetime, Dict[int, Dict[int, Balance]]]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to guild entries with Balance objects (non-errors only)
        """
        time = datetime.now()

        if set_full_fetch:
            self._last_full_fetch[guild_id] = time

        with self._user_lock:
            if users is None:
                users = self._users

            data = {}
            logging.info(f'Fetching data for {len(users)} users {keep_errors=}')
            for user in users:
                if not guild_id or guild_id == user.guild_id or user.guild_id:
                    if user.rekt_on and not force_fetch:
                        balance = Balance(0.0, '$', None)
                    else:
                        balance = user.api.get_balance(datetime)
                    if balance.error:
                        logging.error(f'Error while fetching user {user} balance: {balance.error}')
                        if keep_errors:
                            if user.id not in data:
                                data[user.id] = {}
                            data[user.id][user.guild_id] = balance
                    else:
                        if user.id not in data:
                            data[user.id] = {}
                        data[user.id][user.guild_id] = balance
                        if balance.amount <= self.rekt_threshold and not user.rekt_on:
                            user.rekt_on = time
                            if callable(self.on_rekt_callback):
                                self.on_rekt_callback(user)

        logging.info(f'Done Fetching')
        return time, data

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
                                             and all(data[key] == prev_data[key] for key in data.keys() & prev_data.keys())):
                    if len(data.keys()) < len(prev_data.keys()) or len(data.keys()) == 0:
                        self._user_data.remove((date, data))
                        date = prev_date
                        data = prev_data
                    elif (prev_date, prev_data) in self._user_data:
                        self._user_data.remove((prev_date, prev_data))
                else:
                    user_data_json.append(
                        (round(date.timestamp()), {user_id: {guild_id: data[user_id][guild_id].to_json() for guild_id in data[user_id]} for user_id in data})
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

    def _on_trade(self, client: Client, trade: Trade):
        with self._user_lock:
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
