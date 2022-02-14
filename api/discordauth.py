import os

from http import HTTPStatus

from flask import request, session
from requests_oauthlib import OAuth2Session

from api.database import db, app
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.user import User

from api.app import app

OAUTH2_CLIENT_ID = '939872409517953104'
OAUTH2_CLIENT_SECRET = 'u0Hp5yCS9uDIMYElRMcWl1tzM9iTSIig'
OAUTH2_REDIRECT_URI = 'http://localhost:5000/callback'

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


@app.route('/api/register/discord', methods=["GET"])
def register_discord():
    user = User.query.filter_by(email="jacksn@mail.com").first()
    if user.discorduser:
        return {'msg': 'Discord is already connected'}, HTTPStatus.BAD_REQUEST
    else:
        scope = request.args.get('scope', 'identify')
        discord = make_session(scope=scope.split(' '))
        authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
        session['oauth2_state'] = state
        return {'authorization': authorization_url}


@app.route('/callback')
def callback():
    user = User.query.filter_by(email="jacksn@mail.com").first()
    if request.values.get('error'):
        return request.values['error']
    discord = make_session(state=session.get('oauth2_state'))
    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=request.url)
    session['oauth2_token'] = token
    user_json = discord.get(API_BASE_URL + '/users/@me').json()
    discord_user = DiscordUser.query.filter_by(user_id=user_json['id']).first()
    if not discord_user:
        discord_user = DiscordUser(
            user_id=user_json['id'],
            name=user_json['username']
        )
    else:
        for client in discord_user.clients:
            client.user = user
    user.discorduser = discord_user
    db.session.commit()
    return {'Success'}
