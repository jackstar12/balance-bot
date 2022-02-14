import json
from datetime import timezone, datetime, timedelta
from functools import wraps
from http import HTTPStatus
from typing import List, Tuple, Union, Dict, Callable
from sqlalchemy import or_, and_

import bcrypt
import os
import flask_jwt_extended as flask_jwt
from flask import request, jsonify, redirect, session, url_for
from requests_oauthlib import OAuth2Session

import api.dbutils as dbutils
from api.database import db, app
from api.dbmodels.client import Client
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.user import User
from models.customencoder import CustomEncoder
from usermanager import UserManager

# Create database connection object
jwt = flask_jwt.JWTManager(app)

import api.discordauth

app.config['SECRET_KEY'] = os.environ.get('OAUTH2_CLIENT_SECRET')


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
            access_token = flask_jwt.create_access_token(identity=flask_jwt.get_jwt_identity())
            data = response.get_json()
            if type(data) is dict:
                data["access_token"] = access_token
                response.data = json.dumps(data)
        return response
    except (RuntimeError, KeyError):
        # Case where there is not a valid JWT. Just return the original respone
        return response


def check_args_before_call(callback, arg_names, *args, **kwargs):
    for arg_name, required in arg_names:
        if request.json:
            value = request.json.get(arg_name)
            kwargs[arg_name] = value
            if not value and required:
                return {'msg': f'Missing parameter {arg_name}'}, HTTPStatus.BAD_REQUEST
        else:
            return {'msg': f'Missing parameter {arg_name}'}
    return callback(*args, **kwargs)


def require_json_args(arg_names: List[Tuple[str, bool]]):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            return check_args_before_call(fn, arg_names, *args, **kwargs)
        return wrapper
    return decorator


def create_endpoint(
        route: str,
        methods: Dict[str, Dict[str, Union[List[Tuple[str, bool]], Callable]]],
        jwt_auth=False):

    def wrapper(*args, **kwargs):
        if request.method in methods:
            arg_names = methods[request.method]['ARGS']
            callback = methods[request.method]['CALLBACK']
        else:
            return {'msg': f'This is a bug in the server.'}, HTTPStatus.INTERNAL_SERVER_ERROR
        return check_args_before_call(callback, arg_names, *args, **kwargs)

    if jwt_auth:
        app.route(route, methods=list(methods.keys()))(
            flask_jwt.jwt_required()(wrapper)
        )
    else:
        app.route(route, methods=list(methods.keys()))(
            wrapper
        )


@app.route('/api/register', methods=["POST"])
@require_json_args(arg_names=[('email', True), ('password', True)])
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
        access_token = flask_jwt.create_access_token(identity=email)
        return {'access_token': access_token}, HTTPStatus.CREATED
    else:
        return {'msg': f'Email is already used'}, HTTPStatus.BAD_REQUEST


@app.route('/api/login', methods=["POST"])
@require_json_args(arg_names=[('email', True), ('password', True)])
def login(email: str, password: str):
    user = User.query.filter_by(email=email).first()
    if user:
        if bcrypt.hashpw(password.encode('utf-8'), user.salt.encode('utf-8')).decode('utf-8') == user.password:
            access_token = flask_jwt.create_access_token(identity=email)
            return {'access_token': access_token}
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
    return jsonify(user.serialize()), 200


def register_client(exchange: str,
                    api_key: str,
                    api_secret: str,
                    subaccount: str = None,
                    extra_kwargs: str = None):
    pass


def get_client_query(user: User, client_id: int):
    user_checks = [Client.user_id == user.id]
    if user.discorduser:
        user_checks.append(Client.discord_user_id == user.discorduser.id)
    return Client.query.filter(
        and_(
            Client.id == client_id,
            or_(*user_checks)
        )
    )


def get_client(id: int):
    user = flask_jwt.current_user
    client = get_client_query(user, id).first()
    if client:
        return jsonify(client.serialize(full=False))
    else:
        return {'msg': f'Invalid client id'}, HTTPStatus.BAD_REQUEST


def delete_client(id: int):
    user = flask_jwt.current_user
    get_client_query(user, id).delete()
    db.session.commit()
    return {'msg': 'Success'}


create_endpoint(
    route='/api/client',
    methods={
        'POST': {
            'ARGS': [
                ("exchange", True),
                ("api_key", True),
                ("api_secret", True),
                ("subaccount", False),
                ("extra_kwargs", False)
            ],
            'CALLBACK': register_client
        },
        'GET': {
            'ARGS': [
                ("id", True)
            ],
            'CALLBACK': get_client
        },
        'DELETE': {
            'ARGS': [
                ("id", True)
            ],
            'CALLBACK': delete_client
        }
    },
    jwt_auth=True
)


def init():
    db.init_app(app)
    db.create_all()


def run():
    app.run(host='localhost', port=5000)


if __name__ == '__main__':
    run()
