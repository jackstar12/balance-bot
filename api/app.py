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

from config import CURRENCY_PRECISION
from usermanager import UserManager
from models.customencoder import CustomEncoder
from api.database import db
from api.dbmodels.user import User
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.client import Client
from api.dbmodels.trade import Trade
from api.dbmodels.event import Event

app = Flask(__name__)
app.config['DEBUG'] = False
app.config['JWT_SECRET_KEY'] = 'owcBrtneZ-AgIfGFS3Wel8KXQUjJDr7mA1grv1u7Ra0'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Create database connection object

jwt = flask_jwt.JWTManager(app)

db.init_app(app)
app.app_context().push()
db.create_all(app=app)


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


# api routes
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
