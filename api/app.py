import json
import os
from datetime import timezone, datetime, timedelta
from functools import wraps
from http import HTTPStatus
from typing import List, Tuple, Union, Dict, Callable

import bcrypt
import flask_jwt_extended as flask_jwt
from flask import request, jsonify
from sqlalchemy import or_, and_

import utils
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


jwt = flask_jwt.JWTManager(app)


app.config['SECRET_KEY'] = os.environ.get('OAUTH2_CLIENT_SECRET')
app.config['JWT_TOKEN_LOCATION'] = ['cookies']
app.config['JWT_COOKIE_SECURE'] = False  # True in production
#app.config['JWT_ACCESS_COOKIE_PATH'] = '/api/'
app.config['JWT_COOKE_CSRF_PROTECT'] = True


@jwt.user_lookup_loader
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
            flask_jwt.set_refresh_cookies(response, flask_jwt.create_refresh_token(identity=flask_jwt.get_jwt_identity()))
        return response
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original respone
        return response


@app.route('/api/register', methods=["POST"])
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


@app.route('/api/login', methods=["POST"])
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


@app.route('/api/logout', methods=["POST"])
def logout():
    response = jsonify({"msg": "logout successful"})
    flask_jwt.unset_jwt_cookies(response)
    return response


@app.route('/api/info')
@flask_jwt.jwt_required()
def info():
    user = flask_jwt.get_current_user()
    print(user.discorduser)
    return jsonify(user.serialize(data=False)), 200


def register_client(exchange: str,
                    api_key: str,
                    api_secret: str,
                    subaccount: str = None,
                    extra_kwargs: str = None):
    pass
#    try:
#        exchange_name = exchange_name.lower()
#        exchange_cls = EXCHANGES[exchange_name]
#        if issubclass(exchange_cls, ClientWorker):
#            # Check if required keyword args are given
#            if len(kwargs.keys()) >= len(exchange_cls.required_extra_args) and \
#                    all(required_kwarg in kwargs for required_kwarg in exchange_cls.required_extra_args):
#                client: Client = Client(
#                    api_key=api_key,
#                    api_secret=api_secret,
#                    subaccount=subaccount,
#                    extra_kwargs=kwargs,
#                    exchange=exchange_name
#                )
#                worker = exchange_cls(client)
#                existing_user = dbutils.get_client(user_id=ctx.author.id, guild_id=ctx.guild_id, throw_exceptions=False)
#                if existing_user:
#                    existing_user.api = client
#                    await ctx.send(embed=existing_user.get_discord_embed(client.get_guild(guild)), hidden=True)
#                    logger.info(f'Updated user')
#                    # user_manager.save_registered_users()
#                else:
#                    new_user = DiscordUser(
#                        user_id=ctx.author.id,
#                        name=ctx.author.name,
#                        clients=[client],
#                        global_client=client
#                    )
#                    init_balance = worker.get_balance(datetime.now())
#                    if init_balance.error is None:
#                        if round(init_balance.amount, ndigits=2) == 0.0:
#                            message = f'You do not have any balance in your account. Please fund your account before registering.'
#                            button_row = None
#                        else:
#                            message = f'Your balance: **{init_balance.to_string()}**. This will be used as your initial balance. Is this correct?\nYes will register you, no will cancel the process.'
#
#                            def register_user():
#                                new_user.clients[0].history.append(init_balance)
#                                user_manager._add_worker(worker)
#                                db.session.add(new_user)
#                                db.session.add(client)
#                                db.session.commit()
#                                logger.info(f'Registered new user')
#
#                            button_row = create_yes_no_button_row(
#                                slash,
#                                author_id=ctx.author.id,
#                                yes_callback=register_user,
#                                yes_message="You were successfully registered!",
#                                no_message="Registration cancelled",
#                                hidden=True
#                            )
#                    else:
#                        message = f'An error occured while getting your balance: {init_balance.error}.'
#                        button_row = None
#
#                    await ctx.send(
#                        content=message,
#                        embed=new_user.get_discord_embed(),
#                        hidden=True,
#                        components=[button_row] if button_row else None
#                    )
#
#            else:
#                logger.error(
#                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
#                args_readable = ''
#                for arg in exchange_cls.required_extra_args:
#                    args_readable += f'{arg}\n'
#                raise UserInputError(
#                    f'Need more keyword arguments for exchange {exchange_cls.exchange}.\nRequirements:\n {args_readable}')
#        else:
#            logger.error(f'Class {exchange_cls} is no subclass of ClientWorker!')
#    except KeyError:
#        raise UserInputError(f'Exchange {exchange_name} unknown')


def get_client_query(user: User, client_id: int):
    user_checks = [Client.user_id == user.id]
    if user.discorduser:
        user_checks.append(Client.discord_user_id == user.discorduser.id)
    return Client.query.filter(
        Client.id == client_id,
        or_(*user_checks)
    )


def get_client(id: int = None, currency: str = None):
    user = flask_jwt.current_user

    if not currency:
        currency = '$'

    if id:
        client = get_client_query(user, id).first()
    elif len(user.clients) > 0:
        client = user.clients[0]
    elif user.discorduser:
        client = user.discorduser.global_client
    else:
        client = None
    if client:
        s = client.serialize(full=True, data=False)
        winners, losers = 0, 0

        history = []
        s['daily'] = utils.calc_daily(
            client=client,
            forEach=lambda balance: history.append(balance.serialize(full=True, data=True, currency=currency))
        )
        s['history'] = history

        trades = []
        for trade in client.trades:
            trade = trade.serialize(full=True, data=True)
            if trade['status'] == 'win':
                winners += 1
            elif trade['status'] == 'loss':
                losers += 1
            trades.append(trade)
        s['trades'] = trades

        ratio = winners / (winners + losers) if winners + losers > 0 else 0.5
        s['win_ratio'] = round(ratio, ndigits=3)
        s['winners'] = winners
        s['losers'] = losers
        return jsonify(s)
    else:
        return {'msg': f'Invalid client id'}, HTTPStatus.BAD_REQUEST


def delete_client(id: int):
    user = flask_jwt.current_user
    get_client_query(user, id).delete()
    db.session.commit()
    return {'msg': 'Success'}


apiutils.create_endpoint(
    route='/api/client',
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
                ("currency", False)
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


def get_label(id: int):
    label = Label.query.filter_by(id=id).first()
    if label:
        client = get_client_query(flask_jwt.current_user, label.client_id).first()
        if client:
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
    else:
        return result


apiutils.create_endpoint(
    route='/api/label',
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


def get_trade_query(client_id: int, trade_id: int, label_id: int=None):
    client = get_client_query(flask_jwt.current_user, client_id)
    if client:
        return Trade.query.filter(
            Trade.id == trade_id,
            Trade.client_id == client_id,
            Trade.label_id == label_id if label_id else True
        )


def add_label(client_id: int, trade_id: int, label_id: int):
    trade = get_trade_query(client_id, trade_id, label_id).first()
    if trade:
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
        return {'msg': 'Invalid Client ID'}, HTTPStatus.UNAUTHORIZED


def remove_label(client_id: int, trade_id: int, label_id: int):
    trade = get_trade_query(client_id, trade_id, label_id).first()
    if trade:
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
        return {'msg': 'Invalid Client ID'}, HTTPStatus.UNAUTHORIZED


apiutils.create_endpoint(
    route='/api/label/trade',
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
