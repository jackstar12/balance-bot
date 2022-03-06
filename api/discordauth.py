import os

from http import HTTPStatus

from flask import request, session
from requests_oauthlib import OAuth2Session

from api.database import db, app
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.user import User
import api.apiutils as apiutils

from api.app import app, flask_jwt

OAUTH2_CLIENT_ID = '939872409517953104'
OAUTH2_CLIENT_SECRET = 'u0Hp5yCS9uDIMYElRMcWl1tzM9iTSIig'
OAUTH2_REDIRECT_URI = os.environ.get('DISCORD_AUTH_REDIRECT', 'http://localhost/api/callback')

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

app.config['SECRET_KEY'] = 'u0Hp5yCS9uDIMYElRMcWl1tzM9iTSIig'


if 'http://' in OAUTH2_REDIRECT_URI:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'


def token_updater(token):
    session['oauth2_token'] = token


def make_session(token=None, state=None, scope=None):
    return OAuth2Session(
        client_id=OAUTH2_CLIENT_ID,
        token=token,
        state=state,
        scope=scope,
        redirect_uri=OAUTH2_REDIRECT_URI,
        auto_refresh_kwargs={
            'client_id': OAUTH2_CLIENT_ID,
            'client_secret': OAUTH2_CLIENT_SECRET,
        },
        auto_refresh_url=TOKEN_URL,
        token_updater=token_updater)


@app.route('/api/discord/connect', methods=["GET"])
@flask_jwt.jwt_required()
def register_discord():
    user = flask_jwt.current_user
    if user.discorduser:
        return {'msg': 'Discord is already connected'}, HTTPStatus.BAD_REQUEST
    else:
        discord = make_session(scope=['identify'])
        authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
        session['oauth2_state'] = state
        return {'authorization': authorization_url}, HTTPStatus.OK


@app.route('/api/discord/disconnect', methods=["GET"])
@flask_jwt.jwt_required()
def disconnect_discord():
    user = flask_jwt.current_user
    if not user.discorduser:
        return {'msg': 'Discord is not connected'}, HTTPStatus.BAD_REQUEST
    else:
        user.discord_user_id = None
        user.discord_user = None
        db.session.commit()
        return {'disconnect': True}, HTTPStatus.OK


@app.route('/api/callback')
@flask_jwt.jwt_required()
def callback():
    user = flask_jwt.current_user
    if request.values.get('error'):
        return request.values['error'], HTTPStatus.INTERNAL_SERVER_ERROR
    discord = make_session(state=session.get('oauth2_state'))

    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=request.url)
    session['oauth2_token'] = token

    user_json = discord.get(API_BASE_URL + '/users/@me').json()

    discord_user = DiscordUser.query.filter_by(user_id=user_json['id']).first()
    if not discord_user:
        discord_user = DiscordUser(user_id=user_json['id'])

    discord_user.name = user_json['username']
    discord_user.avatar = user_json['avatar']

    user.discorduser = discord_user

    db.session.commit()
    return {'msg': f'Successfully connected'}, HTTPStatus.OK
