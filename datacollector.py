import json
import os
import typing
import asyncio
import sys
import shutil

import balance
from Exchanges import *
from threading import Lock, Timer
from typing import List, Tuple, Dict, Callable, Optional
from user import User
from datetime import datetime, timedelta
from balance import Balance, balance_from_json
from subprocess import call

import logging


class DataCollector:

    def __init__(self,
                 users: List[User],
                 fetching_interval_hours: int = 4,
                 rekt_threshold: float = 2.5,
                 data_path: str = '',
                 on_rekt_callback: Callable = None):
        super().__init__()
        self.users = users
        self.user_data: List[Tuple[datetime, Dict[int, Balance]]] = []

        self.user_lock = Lock()
        self.data_lock = Lock()

        self.interval_hours = fetching_interval_hours
        self.rekt_threshold = rekt_threshold
        self.data_path = data_path
        self.backup_path = self.data_path + 'backup/'
        self.on_rekt_callback = on_rekt_callback

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
        time = datetime.now()

        self.data_lock.acquire()
        self.user_data.append(self._fetch_data())
        self.data_lock.release()

        self._save_user_data()

        if time.hour == 0:
            pass

        next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                            microsecond=0) + timedelta(hours=self.interval_hours)
        delay = next - time

        timer = Timer(delay.total_seconds(), self.start_fetching)
        timer.start()

    def fetch_data(self, time_tolerance_seconds: float = 60):
        self.data_lock.acquire()
        time, data = self.user_data[len(self.user_data) - 1]
        now = datetime.now()
        if now - time > timedelta(seconds=time_tolerance_seconds):
            time, data = self._fetch_data()
            self.user_data.append((time, data))
        self.data_lock.release()
        return time, data

    def get_user_balance(self, user: User, currency: str = None) -> Balance:

        if currency is None:
            currency = '$'

        time, data = self._fetch_data(users=[user], keep_errors=True)

        result = data[user.id]

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

    def get_latest_user_balance(self, user_id: int, currency: str = None) -> Optional[Balance]:
        result = None

        if currency is None:
            currency = '$'

        self.data_lock.acquire()
        for time, data in reversed(self.user_data):
            if user_id in data:
                user_balance = self.match_balance_currency(data[user_id], currency)
                if user_balance:
                    result = user_balance
                    break
        self.data_lock.release()
        return result

    def get_single_user_data(self,
                             user_id: int,
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
            if user_id in data and start < time < end:
                user_balance = data[user_id]
                user_balance = self.match_balance_currency(user_balance, currency)
                if user_balance:
                    single_user_data.append((time, user_balance))
        self.data_lock.release()
        return single_user_data

    def has_fetched_recently(self, time_tolerance_seconds: int = 60) -> bool:
        self.data_lock.acquire()
        result = datetime.now() - self.user_data[len(self.user_data) - 1][0] < timedelta(seconds=time_tolerance_seconds)
        self.data_lock.release()
        return result

    def clear_user_data(self, user_id: int, start: datetime = None, end: datetime = None):
        self.data_lock.acquire()
        if start is None:
            start = datetime.fromtimestamp(0)
        if end is None:
            end = datetime.now()
        for time, data in self.user_data:
            if user_id in data and start < time < end:
                data.pop(user_id)
        self.data_lock.release()
        self._save_user_data()

    def _fetch_data(self, users: List[User] = None, keep_errors: bool = False) -> Tuple[datetime, Dict[int, Balance]]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to Balance objects (non-errors only)
        """
        self.user_lock.acquire()
        if users is None:
            users = self.users

        time = datetime.now()
        data = {}
        logging.info(f'Fetching data')
        for user in users:
            if user.rekt_on:
                balance = Balance(0.0, '$', None)
            else:
                balance = user.api.get_balance()
            if balance.error:
                logging.error(f'Error while fetching user {user} balance: {balance.error}')
                if keep_errors:
                    data[user.id] = balance
            else:
                data[user.id] = balance
                if balance.amount <= self.rekt_threshold and not user.rekt_on:
                    user.rekt_on = time
                    if callable(self.on_rekt_callback):
                        self.on_rekt_callback(user)
        self.user_lock.release()
        return time, data

    # TODO: Encryption for user data
    def _save_user_data(self):
        self.data_lock.acquire()

        if self._saves_since_backup >= self.interval_hours * 24:
            shutil.copy(self.data_path + 'user_data.json', self.backup_path + "backup_user_data.json")
            self._saves_since_backup = 0
        else:
            self._saves_since_backup += 1

        with open(self.data_path + "user_data.json", "w") as f:
            user_data_json = []
            prev_date, prev_data = datetime.fromtimestamp(0), {}
            for date, data in self.user_data:
                if len(data.keys()) == 0 or ((date - prev_date) < timedelta(minutes=10)
                                             and all(
                            data[key] == prev_data[key] for key in data.keys() & prev_data.keys())):
                    # If all common users have the same balances why bother keeping the one with fewer users?
                    if len(data.keys()) < len(prev_data.keys()) or len(data.keys()) == 0:
                        self.user_data.remove((date, data))
                        date = prev_date
                        data = prev_data
                    else:
                        try:
                            self.user_data.remove((prev_date, prev_data))
                        except ValueError:
                            pass  # Not in list
                else:
                    user_data_json.append(
                        (round(date.timestamp()), {user_id: data[user_id].to_json() for user_id in data})
                    )
                prev_date = date
                prev_data = data

            json.dump(fp=f, obj=user_data_json)

        self.data_lock.release()

    def _load_user_data(self):
        self.data_lock.acquire()

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
                        index = 0
                        index_merge = 0
                        normal_len = len(raw_json)
                        merge_len = len(raw_json_merge)
                        while index_merge < merge_len or index < normal_len:
                            if index < normal_len:
                                ts_normal, data_normal = raw_json[index]
                            if index_merge < merge_len:
                                ts_merge, data_merge = raw_json_merge[index_merge]
                            if ts_normal < ts_merge or index_merge == merge_len:
                                self.user_data.append(
                                    (datetime.fromtimestamp(ts_normal),
                                     {int(user_id): balance_from_json(data_normal[user_id]) for user_id in data_normal})
                                )
                                if index < normal_len:
                                    index += 1
                            elif ts_merge < ts_normal or index == normal_len:
                                self.user_data.append(
                                    (datetime.fromtimestamp(ts_merge),
                                     {int(user_id): balance_from_json(data_merge[user_id]) for user_id in data_merge})
                                )
                                if index_merge < merge_len:
                                    index_merge += 1
                            else:
                                for merge in data_merge:
                                    if merge not in data_normal:
                                        data_normal[merge] = data_merge[merge]
                                self.user_data.append(
                                    (datetime.fromtimestamp(ts_normal),
                                     {int(user_id): balance_from_json(data_normal[user_id]) for user_id in data_normal})
                                )
                                if index < normal_len:
                                    index += 1
                                if index_merge < merge_len:
                                    index_merge += 1
                    else:
                        self.user_data += [
                            (
                                datetime.fromtimestamp(ts),
                                {int(user_id): balance_from_json(data[user_id]) for user_id in data}
                            )
                            for ts, data in raw_json
                        ]
        except FileNotFoundError:
            logging.info('No user data found')
        except json.JSONDecodeError as e:
            logging.error(f'{e}: Error while parsing user data.')

        self.data_lock.release()

    def match_balance_currency(self, balance: Balance, currency: str):
        result = None
        if balance.currency != currency:
            if balance.extra_currencies:
                if currency in balance.extra_currencies:
                    result = Balance(amount=balance.extra_currencies[currency], currency=currency)
        else:
            result = balance

        return result
