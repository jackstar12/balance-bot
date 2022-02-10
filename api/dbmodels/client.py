import abc
import logging
from datetime import datetime
from typing import List, Callable
from urllib.request import Request
from requests import Request, Response, Session
from sqlalchemy.ext.hybrid import hybrid_property

from api.database import db
from api.dbmodels.trade import Trade
from api.dbmodels.balance import Balance
from api.dbmodels.event import Event


class Client(db.Model):
    __tablename__ = 'client'

    # Identification
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    discord_user_id = db.Column(db.Integer, db.ForeignKey('discorduser.id'), nullable=True)

    # User Information
    api_key = db.Column(db.String, nullable=False)
    api_secret = db.Column(db.String, nullable=False)
    exchange = db.Column(db.String, nullable=False)
    subaccount = db.Column(db.String, nullable=True)
    extra_kwargs = db.Column(db.PickleType, nullable=True)

    # Data
    name = db.Column(db.String, nullable=True)
    rekt_on = db.Column(db.DateTime, nullable=True)
    trades = db.relationship('Trade', backref='client_trades', lazy=True)
    history = db.relationship('Balance', backref='client_history', lazy=True)

    required_extra_args: List[str] = []

    @hybrid_property
    def is_global(self):
        return self.discorduser.global_client_id == self.id

    @hybrid_property
    def is_active(self):
        return not all(not event.is_active for event in self.events)

    def get_event_string(self):
        events = ''
        if self.is_global:
            events += 'Global'
        for event in self.events:
            events += f', {event.name}'
        return events
