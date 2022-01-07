import json
import os
import typing
import asyncio
import sys
import shutil


import balance
from threading import Thread
from Exchanges import *
from threading import Lock, Timer
from typing import List, Tuple, Dict, Callable, Optional, Any
from user import User
from datetime import datetime, timedelta
from balance import Balance, balance_from_json
from subprocess import call
from config import CURRENCY_ALIASES

import logging


class DataCollector:

    def __init__(self,
                 users: List[User],
                 fetching_interval_hours: int = 4,
                 rekt_threshold: float = 2.5,
                 data_path: str = '',
                 on_rekt_callback: Callable[[User], Any] = None):
        super().__init__()
        self.users = users
        self.user_data: List[Tuple[datetime, Dict[int, Dict[int, Balance]]]] = []

        self.user_lock = Lock()
        self.data_lock = Lock()

        self.interval_hours = fetching_interval_hours
        self.rekt_threshold = rekt_threshold
        self.data_path = data_path
        self.backup_path = self.data_path + 'backup/'

        if not os.path.exists(self.backup_path):
            os.mkdir(self.backup_path)

        self.on_rekt_callback = on_rekt_callback

        self._last_full_fetch = {}
        self._saves_since_backup = 0
        self._load_user_data()

    def add_user(self, user: User):
        self.user_lock.acquire()
        if user not in self.users:
            self.users.append(user)
        self.user_lock.release()

    def remove_user(self, user: User):
        self.user_lock.acquire()
        if user in self.users:
            self.users.remove(user)
        self.user_lock.release()

    def get_user_data(self):
        return self.user_data

    def start_fetching(self):
        """
        Start fetching data at specified interval
        """

        self.data_lock.acquire()
        self.user_data.append(self._fetch_data(set_full_fetch=True))
        self.data_lock.release()

        self._save_user_data()

        time = datetime.now()
        next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                            microsecond=0) + timedelta(hours=self.interval_hours)
        delay = next - time

        timer = Timer(delay.total_seconds(), self.start_fetching)
        timer.start()

    def fetch_data(self, users: List[User] = None, guild_id: int = None, time_tolerance_seconds: float = 60):
        self.data_lock.acquire()
        time, data = self.user_data[len(self.user_data) - 1]
        if not self._fetched_recently(guild_id, time_tolerance_seconds):
            time, data = self._fetch_data(users=users, guild_id=guild_id, set_full_fetch=True)
            self.user_data.append((time, data))
        self.data_lock.release()
        return time, data

    def get_user_balance(self, user: User, currency: str = None) -> Balance:

        if currency is None:
            currency = '$'

        time, data = self._fetch_data(users=[user], keep_errors=True)

        result = data[user.id][user.guild_id]

        if result.error is None or result.error == '':
            self.data_lock.acquire()
            self.user_data.append((time, data))
            self.data_lock.release()
            matched_balance = self.match_balance_currency(result, currency)
            if matched_balance:
                result = matched_balance
            else:
                result.error = f'User balance does not contain currency {currency}'

        return result

    def get_latest_user_balance(self, user_id: int, guild_id: int = None, currency: str = None) -> Optional[Balance]:
        result = None

        if currency is None:
            currency = '$'

        self.data_lock.acquire()
        for time, data in reversed(self.user_data):
            user_balance = self.get_balance_from_data(data, user_id, guild_id, exact=True)
            if user_balance:
                user_balance = self.match_balance_currency(user_balance, currency)
                if user_balance:
                    result = user_balance
                    break
        self.data_lock.release()
        return result

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
                             currency: str = None) -> List[Tuple[datetime, Balance]]:
        single_user_data = []
        self.data_lock.acquire()

        # Defaults.
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()
        if currency is None:
            currency = '$'

        for time, data in self.user_data:
            if start < time < end:
                user_balance = self.get_balance_from_data(data, user_id, guild_id, exact=True)
                if user_balance:
                    user_balance = self.match_balance_currency(user_balance, currency)
                    if user_balance:
                        single_user_data.append((time, user_balance))
        self.data_lock.release()
        return single_user_data

    def clear_user_data(self,
                        user: User,
                        start: datetime = None,
                        end: datetime = None,
                        remove_all_guilds = False,
                        update_initial_balance = False):

        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()

        new_initial = None
        self.data_lock.acquire()

        if start > self.user_data[0][0]:
            update_initial_balance = False

        for time, data in self.user_data:
            if user.id in data:
                if start <= time <= end:
                    if remove_all_guilds:
                        data.pop(user.id)
                    elif user.guild_id in data[user.id]:
                        data[user.id].pop(user.guild_id)

        self.data_lock.release()

        if update_initial_balance:
            new_initial = None
            self.data_lock.acquire()
            for time, data in self.user_data:
                new_initial = self.get_balance_from_data(data, user.id, user.guild_id, exact=True)
                if new_initial:
                    user.initial_balance = time, new_initial
                    break
            self.data_lock.release()
            if not new_initial:
                user.initial_balance = datetime.now(), self.get_user_balance(user)

        self._save_user_data()

    def _fetched_recently(self, guild_id: int = None, time_tolerance_seconds: float = 60):
        last_fetch = self._last_full_fetch.get(guild_id)
        if not last_fetch:
            last_fetch = self._last_full_fetch.get(None)
        return datetime.now() - last_fetch < timedelta(seconds=time_tolerance_seconds)

    def _fetch_data(self, users: List[User] = None, guild_id: int = None, keep_errors: bool = False, set_full_fetch = False) -> Tuple[datetime, Dict[int, Dict[int,  Balance]]]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to guild entries with Balance objects (non-errors only)
        """
        self.user_lock.acquire()
        time = datetime.now()

        if users is None:
            users = self.users

        if set_full_fetch:
            self._last_full_fetch[guild_id] = time

        data = {}
        logging.info(f'Fetching data for {len(users)} users {keep_errors=}')
        for user in users:
            if not guild_id or guild_id == user.guild_id or user.guild_id:
                if user.rekt_on:
                    balance = Balance(0.0, '$', None)
                else:
                    balance = user.api.get_balance()
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
        self.user_lock.release()
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

        self.data_lock.acquire()

        with open(self.data_path + "user_data.json", "w") as f:
            user_data_json = []
            prev_date, prev_data = datetime.fromtimestamp(0), {}
            for date, data in self.user_data:
                # Data is removed if
                # - it doesn't contain anything
                # - it isn't further than 10 minutes apart from the last timestamp and all common users have the same entries
                if len(data.keys()) == 0 or ((date - prev_date) < timedelta(minutes=10)
                                             and all(data[key] == prev_data[key] for key in data.keys() & prev_data.keys())):
                    if len(data.keys()) < len(prev_data.keys()) or len(data.keys()) == 0:
                        self.user_data.remove((date, data))
                        date = prev_date
                        data = prev_data
                    elif (prev_date, prev_data) in self.user_data:
                        self.user_data.remove((prev_date, prev_data))
                else:
                    user_data_json.append(
                        (round(date.timestamp()), {user_id: {guild_id: data[user_id][guild_id].to_json() for guild_id in data[user_id]} for user_id in data})
                    )
                prev_date = date
                prev_data = data

            json.dump(fp=f, obj=user_data_json)

        self.data_lock.release()

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

        self.data_lock.acquire()
        self.user_data.append((datetime.fromtimestamp(ts), user_data))
        self.data_lock.release()

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
