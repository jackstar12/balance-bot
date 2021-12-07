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
            user_data_json = [
                (date.timestamp(), {user_id: data[user_id].to_json() for user_id in data}) for date, data in self.user_data
            ]
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
                         {int(user_id): Balance(data[user_id].get('amount', 0), data[user_id].get('currency', '$'), None) for user_id in data}) for ts, data in raw_json
                    ]
        except FileNotFoundError:
            logging.info('No user data found')

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

    def _fetch_data(self) -> Tuple[datetime, Dict[int, Balance]]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to Balance objects (non-errors only)
        """
        self.user_lock.acquire()
        time = datetime.now()
        data = {}
        for user in self.users:
            if user.rekt_on is None:
                balance = user.api.getBalance()
                if balance.error is None or balance.error == '':
                    if balance.amount > 0:
                        data[user.id] = balance
                    else:
                        user.rekt_on = time
                        if self.on_rekt_callback:
                            self.on_rekt_callback(user)
                logging.info(f'{user} balance: {balance}')
        self.user_lock.release()
        return time, data

    def fetch_data(self, time_tolerance_seconds: float = 60):
        self.data_lock.acquire()
        time, data = self.user_data[len(self.user_data) - 1]
        now = datetime.now()
        if now - time > timedelta(seconds=time_tolerance_seconds):
            time, data = self._fetch_data()
            self.user_data.append((time, data))
        self.data_lock.release()
        return time, data

    def get_latest_user_balance(self, user_id: int) -> Optional[Balance]:
        result = None
        self.data_lock.acquire()
        for time, data in reversed(self.user_data):
            if user_id in data:
                result = data[user_id]
        self.data_lock.release()
        return result

    def get_single_user_data(self, user_id: int) -> List[Tuple[datetime, Balance]]:
        self.data_lock.acquire()
        single_user_data = []
        for time, data in self.user_data:
            if user_id in data:
                single_user_data.append((time, data[user_id]))
        return single_user_data



