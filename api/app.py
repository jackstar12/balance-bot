import json
from datetime import timezone, datetime, timedelta
from functools import wraps
from http import HTTPStatus
from typing import List, Tuple

import bcrypt
import flask_jwt_extended as flask_jwt
from flask import request, jsonify, redirect

import api.dbutils as dbutils
from api.database import db, app
from api.dbmodels.client import Client
from api.dbmodels.user import User
from models.customencoder import CustomEncoder
from usermanager import UserManager

# Create database connection object
jwt = flask_jwt.JWTManager(app)


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


def required_params(name: str, arg_names: List[Tuple[str, bool]]):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            for arg_name, required in arg_names:
                value = request.json.get(arg_name)
                kwargs[arg_name] = value
                if not value and required:
                    return {'msg': f'Missing parameter {arg_name}'}, HTTPStatus.BAD_REQUEST
            return fn(*args, **kwargs)
        return wrapper
    return decorator


@app.route('/api/register/discord', methods=["GET"])
@flask_jwt.jwt_required()
def register_discord():
    user = flask_jwt.current_user
    if user.discorduser:
        return {'msg': 'Discord is already connected'}, HTTPStatus.BAD_REQUEST
    else:
        return redirect()


@app.route('/api/register', methods=["POST"])
@required_params(name='register', arg_names=[('email', True), ('password', True)])
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
@required_params(name='login', arg_names=[('email', True), ('password', True)])
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
    json = user.serialize()
    return json, 200
    pass


@app.route('/api/discord', methods=["POST", "GET"])
@flask_jwt.jwt_required()
def discord():
    if request.method == 'GET':
        discord_user = flask_jwt.current_user.discorduser
        if discord_user:
            json = discord_user.serialize()
            return json, 200
        else:
            return {'msg': 'No discord account connected'}
    elif request.method == 'POST':
        pass


@app.route('/api/client/register')
@flask_jwt.jwt_required()
@required_params(name="client_register", arg_names=[
    ("exchange", True),
    ("api_key", True),
    ("api_secret", True),
    ("subaccount", False),
    ("extra_kwargs", False),
])
def client_register(exchange: str,
                    api_key: str,
                    api_secret: str,
                    subaccount: str = None,
                    extra_kwargs: dict = None):
    pass



@app.route('/api/client')
@flask_jwt.jwt_required()
def client():
    user = flask_jwt.get_current_user()
    id = request.args.get('id')
    if id:
        client = Client.query.filter_by(id=id).all()
    else:
        return {'msg': 'ID Parameter required'}, 401


# api routes
@app.route('/api/user')
@flask_jwt.jwt_required()
def data():
    um = UserManager()
    user = dbutils.get_user
    return json.dumps(um.get_single_user_data(user_id=466706956158107649, guild_id=None), cls=CustomEncoder)


@app.route('/api/')


@jwt.user_lookup_loader
def callback(token, payload):
    email = payload.get('sub')
    return User.query.filter_by(email=email).first()



@app.route('/api/trades')
@flask_jwt.jwt_required()
def trades():
    um = UserManager()
    return json.dumps(um.get_user(user_id=466706956158107649, guild_id=None).api.trades, cls=CustomEncoder)


def init():
    db.init_app(app)
    db.create_all()


def run():
    app.run(host='localhost', port=5000)


if __name__ == '__main__':
    run()