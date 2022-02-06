import abc
import json
import logging
import secrets
from datetime import datetime
from typing import List, Tuple, Optional, Dict, Any, Callable
from requests import Request, Response, Session

from flask import Flask, render_template_string, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
import sqlalchemy.schema as schema
import sqlalchemy.sql.sqltypes as types
import flask_jwt_extended as flask_jwt
from sqlalchemy_utils import database_exists, create_database

from Models.balance import Balance
from usermanager import UserManager
from Models.customencoder import CustomEncoder

app = Flask(__name__)
app.config['DEBUG'] = True
app.config['JWT_SECRET_KEY'] = 'owcBrtneZ-AgIfGFS3Wel8KXQUjJDr7mA1grv1u7Ra0'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Create database connection object
db = SQLAlchemy(app)

jwt = flask_jwt.JWTManager(app)


class User(db.Model):
    id = schema.Column(types.Integer, primary_key=True)
    email = schema.Column(types.String, unique=True, nullable=False)
    password = schema.Column(types.String, unique=True, nullable=False)
    clients = schema.Column(types.ARRAY(types.Integer))


class Trade(db.Model):
    client_id = schema.Column(types.Integer, schema.ForeignKey('client.id'), primary_key=True)
    symbol = schema.Column(types.String, nullable=False)
    price = schema.Column(types.Float, nullable=False)
    qty = schema.Column(types.Float, nullable=False)
    side = schema.Column(types.String, nullable=False)
    type = schema.Column(types.String, nullable=False)
    time = schema.Column(types.DateTime, nullable=False)


class Client(db.Model):
    id = schema.Column(types.Integer, primary_key=True)
    api_key = schema.Column(types.String, nullable=False)
    api_secret = schema.Column(types.String, nullable=False)
    exchange = schema.Column(types.String, nullable=False)
    subaccount = schema.Column(types.String, nullable=True)

    rekt_on = schema.Column(types.DateTime, nullable=True)
    initial_balance = schema.Column(types.TupleType(types.DateTime, db.relationship('Balance', backref='client', lazy=True)))
    trades: List[Trade] = db.relationship('Trade', backref='client', lazy=True)
    history = db.relationship('Balance', backref='client', lazy=True)

    required_extra_args: List[str]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._session = Session()
        self._on_trade = None
        self._identifier = id

    @abc.abstractmethod
    def get_balance(self):
        logging.error(f'Exchange {self.exchange} does not implement get_balance!')

    def on_trade(self, callback: Callable[[str, Trade], None], identifier):
        self._on_trade = callback
        self._identifier = identifier

    @abc.abstractmethod
    def _sign_request(self, request: Request):
        logging.error(f'Exchange {self.exchange} does not implement _sign_request!')

    @abc.abstractmethod
    def _process_response(self, response: Response):
        logging.error(f'Exchange {self.exchange} does not implement _process_response')

    def _request(self, request: Request, sign=True):
        if sign:
            self._sign_request(request)
        prepared = request.prepare()
        response = self._session.send(prepared)
        return self._process_response(response)

    def repr(self):
        r = f'Exchange: {self.exchange}\n' \
               f'API Key: {self.api_key}\n' \
               f'API secret: {self.api_secret}'
        if self.subaccount != '':
            r += f'\nSubaccount: {self.subaccount}'

        return r


class Balance(db.Model):
    id = schema.Column(types.Integer, schema.ForeignKey('client.id'), primary_key=True)
    amount = schema.Column(types.Float, nullable=False)
    currency = schema.Column(types.String, nullable=False)
    error = schema.Column(types.String, nullable=True)
    extra_currencies = db.Table(schema.Column('currency', types.String), schema.Column('amount', types.Float))

    def to_json(self, currency=False):
        json = {
            'amount': self.amount,
        }
        if self.error:
            json['error'] = self.error
        if currency or self.currency != '$':
            json['currency'] = self.currency
        if self.extra_currencies:
            json['extra_currencies'] = self.extra_currencies
        return json

    def to_string(self, display_extras=True):
        string = f'{round(self.amount, ndigits=CURRENCY_PRECISION.get(self.currency, 3))}{self.currency}'

        if self.extra_currencies and display_extras:
            first = True
            for currency in self.extra_currencies:
                string += f'{" (" if first else "/"}{round(self.extra_currencies[currency], ndigits=CURRENCY_PRECISION.get(currency, 3))}{currency}'
                first = False
            if not first:
                string += ')'

        return string



db.create_all()


@app.route('/api/login', methods=["POST"])
def login():
    email = request.args.get('email')
    password = request.args.get('password')
    user = User.query.filter_by(email=email).first()
    if user.password == password:
        access_token = flask_jwt.create_access_token(identity=email)
        return {'access_token': access_token}
    else:
        return {'msg': 'Wrong Email or password'}, 401


@app.route('/api/logout', methods=["POST"])
def logout():
    response = jsonify({"msg": "logout successful"})
    flask_jwt.unset_jwt_cookies(response)
    return response


# API routes
@app.route('/api/data')
@flask_jwt.jwt_required()
def data():

    um = UserManager()
    return json.dumps(um.get_single_user_data(user_id=466706956158107649, guild_id=None), cls=CustomEncoder)


@jwt.user_lookup_loader
def callback(token, payload):
    email = payload.get('sub')
    return User.query.filter_by(email=email).first()


@app.route('/api/clients')
@flask_jwt.jwt_required()
def clients():
    user = flask_jwt.get_current_user()


@app.route('/api/trades')
@flask_jwt.jwt_required()
def trades():
    um = UserManager()
    return json.dumps(um.get_user(user_id=466706956158107649, guild_id=None).api.trades, cls=CustomEncoder)


def run():
    app.run(host='localhost', port=5000)


if __name__ == '__main__':
    run()
