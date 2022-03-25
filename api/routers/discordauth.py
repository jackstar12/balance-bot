import os

from http import HTTPStatus

from flask import request, session, redirect
from requests_oauthlib import OAuth2Session

from api.database import db, app
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.user import User
import api.apiutils as apiutils

from api.app import app, flask_jwt
from fastapi import APIRouter

OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID')
OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET')
OAUTH2_REDIRECT_URI = os.environ.get('DISCORD_AUTH_REDIRECT')

assert OAUTH2_CLIENT_SECRET
assert OAUTH2_CLIENT_ID
assert OAUTH2_REDIRECT_URI

router = APIRouter(
    prefix="/discord",
    tags=["discord"],
    dependencies=[],
    responses={400: {"msg": "Invalid Discord Account"}}
)


API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'
app.config['SECRET_KEY'] = OAUTH2_CLIENT_SECRET

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


@router.get('/connect')
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


@router.get('/disconnect')
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


@router.get('/callback')
@flask_jwt.jwt_required()
def callback():
    user = flask_jwt.current_user
    if request.values.get('error'):
        return request.values['error'], HTTPStatus.INTERNAL_SERVER_ERROR
    discord = make_session(state=session.get('oauth2_state'))

    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=request.url
    )
    session['oauth2_token'] = token

    user_json = discord.get(API_BASE_URL + '/users/@me').json()

    discord_user = DiscordUser.query.filter_by(user_id=user_json['id']).first()
    if not discord_user:
        discord_user = DiscordUser(user_id=user_json['id'])

    discord_user.name = user_json['username']
    discord_user.avatar = user_json['avatar']

    user.discorduser = discord_user

    db.session.commit()
    return redirect('/app/profile')
