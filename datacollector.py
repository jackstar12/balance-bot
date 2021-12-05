from Exchanges import *
from threading import Thread, Lock, Timer
from typing import List, Tuple, Dict
from user import User
from datetime import datetime, timedelta

import logging


class DataCollector:

    def __init__(self, users: List[User]):
        super().__init__()
        self.users = users
        self.user_lock = Lock()
        self.user_data: List[Tuple[datetime, dict]] = []

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

    def fetch_data(self, interval_hours: int = 4):

        time = datetime.now()

        self.user_lock.acquire()

        data = {}
        for user in self.users:
            balance = user.api.getBalance()
            data[user.id] = balance
            logging.info(f'User {user} balance: {balance}')
        self.user_data.append((time, data))

        time = datetime.now()
        if time.hour == 0:
            pass

        self.user_lock.release()

        next = time.replace(hour=(time.hour-time.hour % interval_hours), minute=0, second=0, microsecond=0) + timedelta(hours=interval_hours)
        delay = next - time
        delay = timedelta(minutes=1)

        timer = Timer(delay.total_seconds(), self.fetch_data)
        timer.start()

