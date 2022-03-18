import json
import logging
import os
from datetime import timezone, datetime, timedelta
from functools import wraps
from http import HTTPStatus
from typing import List, Tuple, Union, Dict, Callable, Optional
from config import EXCHANGES

import bcrypt
import flask_jwt_extended as flask_jwt
import jwt
from flask import request, jsonify
from sqlalchemy import or_, and_

import utils
from api import dbutils
from api.database import db, app, migrate

import api.dbutils
import api.apiutils as apiutils
from api.dbmodels.client import Client
from api.dbmodels.user import User
from api.dbmodels.trade import Trade
from api.dbmodels.label import Label
from api.dbmodels.event import Event
from api.dbmodels.execution import Execution
import api.discordauth
from clientworker import ClientWorker
from usermanager import UserManager

jwt_manager = flask_jwt.JWTManager(app)

app.config['JWT_SECRET_KEY'] = os.environ.get('JWT_SECRET')
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_CSRF_METHODS'] = []
app.config['JWT_COOKIE_CSRF_PROTECT'] = True
app.config['JWT_COOKIE_SECURE'] = True  # True in production


@jwt_manager.user_lookup_loader
def callback(token, payload):
    email = payload.get('sub')
    return User.query.filter_by(email=email).first()


@app.after_request
def refresh_expiring_jwts(response):
    try:
        exp_timestamp = flask_jwt.get_jwt()["exp"]
        now = datetime.now(timezone.utc)
        target_timestamp = datetime.timestamp(now + timedelta(minutes=30))
        if target_timestamp > exp_timestamp:
            flask_jwt.set_access_cookies(response, flask_jwt.create_access_token(identity=flask_jwt.get_jwt_identity()))
            flask_jwt.set_refresh_cookies(response,
                                          flask_jwt.create_refresh_token(identity=flask_jwt.get_jwt_identity()))
        return response
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original respone
        return response


@app.route('/api/v1/register', methods=["POST"])
@apiutils.require_args(arg_names=[('email', True), ('password', True)])
def register(email: str, password: str):
    user = User.query.filter_by(email=email).first()
    if not user:
        salt = bcrypt.gensalt()
        new_user = User(
            email=email,
            salt=salt.decode('utf-8'),
            password=bcrypt.hashpw(password.encode(), salt).decode('utf-8')
        )
        db.session.add(new_user)
        db.session.commit()
        resp = jsonify({'login': True})
        flask_jwt.set_access_cookies(resp, flask_jwt.create_access_token(identity=new_user.email))
        flask_jwt.set_refresh_cookies(resp, flask_jwt.create_refresh_token(identity=new_user.email))
        return resp
    else:
        return {'msg': f'Email is already used'}, HTTPStatus.BAD_REQUEST


@app.route('/api/v1/login', methods=["POST"])
@apiutils.require_args(arg_names=[('email', True), ('password', True)])
def login(email: str, password: str):
    user = User.query.filter_by(email=email).first()
    if user:
        if bcrypt.hashpw(password.encode('utf-8'), user.salt.encode('utf-8')).decode('utf-8') == user.password:
            resp = jsonify({'login': True})
            flask_jwt.set_access_cookies(resp, flask_jwt.create_access_token(identity=user.email))
            flask_jwt.set_refresh_cookies(resp, flask_jwt.create_refresh_token(identity=user.email))
            return resp
    return {'msg': 'Wrong Email or password'}, 401


@app.route('/api/v1/logout', methods=["POST"])
def logout():
    response = jsonify({"msg": "logout successful"})
    flask_jwt.unset_jwt_cookies(response)
    return response


@app.route('/api/v1/info')
@flask_jwt.jwt_required()
def info():
    return jsonify(flask_jwt.current_user.serialize(full=True, data=False)), 200


def register_client(exchange: str,
                    api_key: str,
                    api_secret: str,
                    subaccount: str = None,
                    **kwargs):
    try:
        exchange_cls = EXCHANGES[exchange]
        if issubclass(exchange_cls, ClientWorker):
            # Check if required keyword args are given
            if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and \
                    all(required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
                client = Client(
                    api_key=api_key,
                    api_secret=api_secret,
                    subaccount=subaccount,
                    extra_kwargs=kwargs,
                    exchange=exchange
                )
                worker = exchange_cls(client)
                init_balance = worker.get_balance(datetime.now())
                if init_balance.error is None:
                    if round(init_balance.amount, ndigits=2) == 0.0:
                        return {
                            'msg': f'You do not have any balance in your account. Please fund your account before registering.'}
                    else:
                        payload = client.serialize(full=True, data=True)
                        # TODO: CHANGE THIS
                        payload['api_secret'] = client.api_secret
                        return {
                                   'msg': 'Success',
                                   'token': jwt.encode(payload, app.config['JWT_SECRET_KEY'], algorithm='HS256'),
                                   'balance': init_balance.amount
                               }, HTTPStatus.OK
                else:
                    return {
                               'msg': f'An error occured while getting your balance: {init_balance.error}.'}, HTTPStatus.BAD_REQUEST
            else:
                logging.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
                args_readable = '\n'.join(exchange_cls.required_extra_args)
                return {
                           'msg': f'Need more keyword arguments for exchange {exchange_cls.exchange}.\nRequirements:\n {args_readable}',
                           'code': 40100
                       }, HTTPStatus.BAD_REQUEST

        else:
            logging.error(f'Class {exchange_cls} is no subclass of ClientWorker!')
    except KeyError:
        return {'msg': f'Exchange {exchange} unknown'}, HTTPStatus.BAD_REQUEST


def get_client_query(user: User, client_id: int):
    user_checks = [Client.user_id == user.id]
    if user.discorduser:
        user_checks.append(Client.discord_user_id == user.discorduser.id)
    return Client.query.filter(
        Client.id == client_id,
        or_(*user_checks)
    )


def get_client(id: int = None, currency: str = None, since: datetime = None, to: datetime = None):
    user = flask_jwt.current_user

    if not currency:
        currency = '$'

    if id:
        client: Optional[Client] = get_client_query(user, id).first()
    elif len(user.clients) > 0:
        client: Optional[Client] = user.clients[0]
    elif user.discorduser:
        client: Optional[Client] = user.discorduser.global_client
    else:
        client = None
    if client:
        s = client.serialize(full=True, data=False)

        if not since:
            since = request.cookies.get('client-last-fetch', datetime.fromtimestamp(0))

        if not to:
            to = datetime.now()

        history = []
        s['daily'] = utils.calc_daily(
            client=client,
            forEach=lambda balance: history.append(balance.serialize(full=True, data=True, currency=currency)),
            throw_exceptions=False,
            since=since,
            to=to
        )
        s['history'] = history

        def ratio(a: float, b: float):
            return round(a / (a + b), ndigits=3) if a + b > 0 else 0.5

        winning_days, losing_days = 0, 0
        for day in s['daily']:
            if day[2] > 0:
                winning_days += 1
            elif day[2] < 0:
                losing_days += 1

        s['daily_win_ratio'] = ratio(winning_days, losing_days)
        s['winning_days'] = winning_days
        s['losing_days'] = losing_days

        trades = []
        winners, losers = 0, 0
        avg_win, avg_loss = 0.0, 0.0
        for trade in client.trades:
            if since <= trade.initial.time <= to:
                trade = trade.serialize(data=True)
                if trade['status'] == 'win':
                    winners += 1
                    avg_win += trade['realized_pnl']
                elif trade['status'] == 'loss':
                    losers += 1
                    avg_loss += trade['realized_pnl']
                trades.append(trade)

        s['trades'] = trades
        s['win_ratio'] = ratio(winners, losers)
        s['winners'] = winners
        s['losers'] = losers
        s['avg_win'] = avg_win
        s['avg_loss'] = avg_loss

        response = jsonify(s)

        response.set_cookie('client-last-fetch', value=str(datetime.now().timestamp()), expires='session')

        return response
    else:
        return {'msg': f'Invalid client id', 'code': 40000}, HTTPStatus.BAD_REQUEST


def delete_client(id: int):
    user = flask_jwt.current_user
    get_client_query(user, id).delete()
    db.session.commit()
    return {'msg': 'Success'}, HTTPStatus.OK


apiutils.create_endpoint(
    route='/api/v1/client',
    methods={
        'POST': {
            'args': [
                ("exchange", True),
                ("api_key", True),
                ("api_secret", True),
                ("subaccount", False),
                ("extra_kwargs", False)
            ],
            'callback': register_client
        },
        'GET': {
            'args': [
                ("id", False),
                ("currency", False),
                ("since", False),
                ("to", False)
            ],
            'callback': get_client
        },
        'DELETE': {
            'args': [
                ("id", True)
            ],
            'callback': delete_client
        }
    },
    jwt_auth=True
)


@app.route('/api/v1/client/confirm', methods=["POST"])
@flask_jwt.jwt_required()
@apiutils.require_args(arg_names=[('token', True)])
def confirm_client(token: str):
    client_json = jwt.decode(token, app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
    print(client_json)
    try:
        client = Client(**client_json)
        flask_jwt.current_user.clients.append(client)
        db.session.add(client)
        db.session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    except TypeError:
        return {'msg': 'Internal Error'}, HTTPStatus.INTERNAL_SERVER_ERROR


def get_label(id: int):
    label: Label = Label.query.filter_by(id=id).first()
    user: User = flask_jwt.current_user
    if label:
        if label.user_id == user.id:
            return label
        else:
            return {'msg': 'You are not allowed to delete this Label'}, HTTPStatus.UNAUTHORIZED
    else:
        return {'msg': 'Invalid ID'}, HTTPStatus.BAD_REQUEST


def create_label(name: str, color: str):
    label = Label(name=name, color=color, user_id=flask_jwt.current_user.id)
    db.session.add(label)
    db.session.commit()
    return jsonify(label.serialize()), HTTPStatus.OK


def delete_label(id: int):
    result = get_label(id)
    if isinstance(result, Label):
        Label.query.filter_by(id=id).delete()
        db.session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return result


def update_label(id: int, name: str = None, color: str = None):
    result = get_label(id)
    if isinstance(result, Label):
        if name:
            result.name = name
        if color:
            result.color = color
        db.session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return result


apiutils.create_endpoint(
    route='/api/v1/label',
    methods={
        'POST': {
            'args': [
                ("name", True),
                ("color", True)
            ],
            'callback': create_label
        },
        'PATCH': {
            'args': [
                ("id", True),
                ("name", False),
                ("color", False)
            ],
            'callback': update_label
        },
        'DELETE': {
            'args': [
                ("id", True),
            ],
            'callback': delete_label
        }
    },
    jwt_auth=True
)


def get_trade_query(client_id: int, trade_id: int, label_id: int = None):
    client = get_client_query(flask_jwt.current_user, client_id)
    if client:
        return Trade.query.filter(
            Trade.id == trade_id,
            Trade.client_id == client_id,
            Trade.label_id == label_id if label_id else True
        )
    else:
        return {'msg': 'Invalid Client ID'}, HTTPStatus.UNAUTHORIZED


def add_label(client_id: int, trade_id: int, label_id: int):
    trade = get_trade_query(client_id, trade_id, label_id).first()
    if isinstance(trade, Trade):
        label = Label.query.filter(
            Label.id == label_id,
            Label.client_id == client_id
        ).first()
        if label:
            if label not in trade.labels:
                trade.labels.append(label)
            else:
                return {'msg': 'Trade already has this label'}, HTTPStatus.BAD_REQUEST
        else:
            return {'msg': 'Invalid Label ID'}, HTTPStatus.BAD_REQUEST
    else:
        return trade


def remove_label(client_id: int, trade_id: int, label_id: int):
    trade = get_trade_query(client_id, trade_id, label_id).first()
    if isinstance(trade, Trade):
        label = Label.query.filter(
            Label.id == label_id,
            Label.client_id == client_id
        ).first()
        if label:
            if label in trade.labels:
                trade.labels.remove(label)
            else:
                return {'msg': 'Trade already has this label'}, HTTPStatus.BAD_REQUEST
        else:
            return {'msg': 'Invalid Label ID'}, HTTPStatus.BAD_REQUEST
    else:
        return trade


def set_labels(client_id: int, trade_id: int, label_ids: List[int]):
    trade = get_trade_query(client_id, trade_id).first()
    if isinstance(trade, Trade):
        if len(label_ids) > 0:
            trade.labels = Label.query.filter(
                or_(
                    Label.id == label_id for label_id in label_ids
                ),
                Label.user_id == flask_jwt.current_user.id
            ).all()
        else:
            trade.labels = []
        db.session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    else:
        return trade


apiutils.create_endpoint(
    route='/api/v1/label/trade',
    methods={
        'POST': {
            'args': [
                ("client_id", True),
                ("trade_id", True),
                ("label_id", True)
            ],
            'callback': add_label
        },
        'DELETE': {
            'args': [
                ("client_id", True),
                ("trade_id", True),
                ("label_id", True)
            ],
            'callback': remove_label
        },
        'PATCH': {
            'args': [
                ("client_id", True),
                ("trade_id", True),
                ("label_ids", True)
            ],
            'callback': set_labels
        }
    },
    jwt_auth=True
)

db.init_app(app)
migrate.init_app(app, db)
db.create_all()


def run():
    app.run(host='localhost', port=5000)


if __name__ == '__main__':
    run()
