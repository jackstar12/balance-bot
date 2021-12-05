import json

from Exchanges import *
from threading import Lock, Timer
from typing import List, Tuple, Dict
from user import User
from datetime import datetime, timedelta
from balance import Balance

import logging


class DataCollector:

    def __init__(self, users: List[User], fetching_interval_hours: int = 4):
        super().__init__()
        self.users = users
        self.user_lock = Lock()
        self.data_lock = Lock()
        self.user_data: List[Tuple[datetime, Dict[int, Balance]]] = []
        self.interval_hours = fetching_interval_hours
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

        with open("user_data.json", "w") as f:
            user_data_json = [
                (date.timestamp(), {user_id: data[user_id].to_json() for user_id in data}) for date, data in self.user_data
            ]
            json.dump(fp=f, obj=user_data_json, indent=3)

        self.data_lock.release()

    def load_user_data(self):
        self.data_lock.acquire()

        with open("user_data.json", "r") as f:
            raw_json = json.load(fp=f)
            if raw_json:
                self.user_data = [
                    (datetime.fromtimestamp(ts),
                     {int(user_id): Balance(data[user_id]['amount'], data[user_id]['currency'], None) for user_id in data}) for ts, data in raw_json
                ]

        self.data_lock.release()

    def start_fetching(self):
        """
        Start fetching data at specified interval
        """

        time = datetime.now()

        self.data_lock.acquire()
        self.user_data.append(self.fetch_data())
        self.data_lock.release()

        self.save_user_data()

        if time.hour == 0:
            pass

        next = time.replace(hour=(time.hour - time.hour % self.interval_hours), minute=0, second=0,
                            microsecond=0) + timedelta(hours=self.interval_hours)
        delay = next - time

        timer = Timer(delay.total_seconds(), self.start_fetching)
        timer.start()

    def fetch_data(self) -> Tuple[datetime, Dict[int, Balance]]:
        """
        :return:
        Tuple with timestamp and Dictionary mapping user ids to Balance objects (non-errors only)
        """
        self.user_lock.acquire()
        time = datetime.now()
        data = {}
        for user in self.users:
            balance = user.api.getBalance()
            if balance.error is None or balance.error == '':
                data[user.id] = balance
            logging.info(f'{user} balance: {balance}')
        self.user_lock.release()
        return time, data
