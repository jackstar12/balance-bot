from Exchanges import *
from threading import Thread, Lock, Timer
from typing import List
from user import User
from datetime import datetime, timedelta

import logging


class DataCollector:

    def __init__(self, users: List[User]):
        super().__init__()
        self.users = users
        self.user_lock = Lock()
        self.user_data = {}

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
        pass

    def fetch_data(self):

        time = datetime.now()

        self.user_lock.acquire()
        for user in self.users:
            balance = user.api.getBalance()
            if user.id not in self.user_data:
                self.user_data[user.id] = {}
            self.user_data[user.id][str(time)] = balance
            logging.info(f'User {user} balance: {balance}')

        time = datetime.now()
        if time.hour == 0:
            pass

        self.user_lock.release()

        next = time.replace(hour=(time.hour-time.hour % 4), minute=0, second=0, microsecond=0) + timedelta(hours=4)
        delay = next - time

        timer = Timer(delay.total_seconds(), self.fetch_data)
        timer.start()

