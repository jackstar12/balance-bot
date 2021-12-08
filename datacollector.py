import json
import os
import typing
import asyncio

from Exchanges import *
from threading import Lock, Timer
from typing import List, Tuple, Dict, Callable, Optional
from user import User
from datetime import datetime, timedelta
from balance import Balance

import logging


class DataCollector:

    def __init__(self,
                 users: List[User],
                 fetching_interval_hours: int = 4,
                 data_path: str = '',
                 on_rekt_callback: Callable = None):
        super().__init__()
        self.users = users
        self.user_data: List[Tuple[datetime, Dict[int, Balance]]] = []

        self.user_lock = Lock()
        self.data_lock = Lock()

        self.interval_hours = fetching_interval_hours
        self.data_path = data_path
        self.backup_path = self.data_path + '/backup'
        self.on_rekt_callback = on_rekt_callback

        self.load_user_data()

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

    # TODO: Encryption for user data
    def save_user_data(self):
        self.data_lock.acquire()

        with open(self.data_path + "user_data.json", "w") as f:
            user_data_json = []
            prev_date, prev_data = datetime.fromtimestamp(0), {}
            for date, data in self.user_data:
                if (date - prev_date) < timedelta(minutes=10) and all(data[key] == prev_data[key] for key in data.keys() & prev_data.keys()):
                    # If all common users have the same balances why bother keeping the one with fewer users?
                    if all(data[key] == prev_data[key] for key in data.keys() & prev_data.keys()):
                        if len(data.keys()) < len(prev_data.keys()):
                            self.user_data.remove((date, data))
                            date = prev_date,
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

    def load_user_data(self):
        self.data_lock.acquire()

        try:
            with open(self.data_path + "user_data.json", "r") as f:
                raw_json = json.load(fp=f)
                if raw_json:
                    self.user_data += [
                        (datetime.fromtimestamp(ts),
                         {int(user_id): Balance(round(data[user_id].get('amount', 0), ndigits=3), data[user_id].get('currency', '$'), None) for user_id in data}) for ts, data in raw_json
                    ]
        except FileNotFoundError:
            logging.info('No user data found')
        except json.JSONDecodeError as e:
            logging.error(f'{e}: Error while parsing user data.')

        self.data_lock.release()

    def start_fetching(self):
        """
        Start fetching data at specified interval
        """
        time = datetime.now()

        self.data_lock.acquire()
        self.user_data.append(self._fetch_data())
        self.data_lock.release()

        self.save_user_data()

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

    def get_user_balance(self, user: User) -> Balance:
        time, data = self._fetch_data(users=[user], keep_errors=True)

        if data[user.id].error is None or data[user.id].error == '':
            self.data_lock.acquire()
            self.user_data.append((time, data))
            self.data_lock.release()

        return data[user.id]

    def get_latest_user_balance(self, user_id: int) -> Optional[Balance]:
        result = None
        self.data_lock.acquire()
        for time, data in reversed(self.user_data):
            if user_id in data:
                result = data[user_id]
                break
        self.data_lock.release()
        return result

    def get_single_user_data(self, user_id: int, start: datetime = None, end: datetime = None) -> List[Tuple[datetime, Balance]]:
        single_user_data = []
        self.data_lock.acquire()
        for time, data in self.user_data:
            if user_id in data:
                single_user_data.append((time, data[user_id]))
        self.data_lock.release()
        return single_user_data

    def has_fetched_recently(self, time_tolerance_seconds: int = 60) -> bool:
        self.data_lock.acquire()
        result = datetime.now() - self.user_data[len(self.user_data) - 1][0] < timedelta(seconds=time_tolerance_seconds)
        self.data_lock.release()
        return result

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
                balance = user.api.getBalance()
            if balance.error is None or balance.error == '' or keep_errors:
                data[user.id] = balance
                if balance == 0.0 and not user.rekt_on:
                    user.rekt_on = time
                    if callable(self.on_rekt_callback):
                        self.on_rekt_callback(user)
        self.user_lock.release()
        return time, data
