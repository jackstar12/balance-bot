import os

from http import HTTPStatus
from typing import Optional

from requests_oauthlib import OAuth2Session
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, JSONResponse

from balancebot.api.database import session
from balancebot.api.database_async import async_session
from balancebot.api.dbmodels.discorduser import DiscordUser
from balancebot.api.dbmodels.user import User
from balancebot.api.dependencies import current_user

from fastapi import APIRouter, Depends, Request

OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID')
OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET')
OAUTH2_REDIRECT_URI = os.environ.get('DISCORD_AUTH_REDIRECT')

assert OAUTH2_CLIENT_SECRET
assert OAUTH2_CLIENT_ID
assert OAUTH2_REDIRECT_URI

router = APIRouter(
    prefix="/discord",
    tags=["discord"],
    dependencies=[Depends(current_user)],
    responses={400: {"msg": "Invalid Discord Account"}}
)

API_BASE_URL = os.environ.get('API_BASE_URL', 'https://discordapp.com/api')
AUTHORIZATION_BASE_URL = API_BASE_URL + '/oauth2/authorize'
TOKEN_URL = API_BASE_URL + '/oauth2/token'

if 'http://' in OAUTH2_REDIRECT_URI:
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = 'true'


def token_updater(request: Request):
    def update(token):
        request.session['oauth2_token'] = token
    return update


def make_session(*, token=None, state=None, scope=None, request: Request = None):
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
        token_updater=token_updater(request)
    )


@router.get('/connect')
def register_discord(request: Request, user: User = Depends(current_user)):
    if user.discorduser:
        return {'msg': 'Discord is already connected'}, HTTPStatus.BAD_REQUEST
    else:
        discord = make_session(scope=['identify'], request=request)
        authorization_url, state = discord.authorization_url(AUTHORIZATION_BASE_URL)
        request.session['oauth2_state'] = state
        return JSONResponse(
            {'authorization': authorization_url}
        )


@router.get('/disconnect')
async def disconnect_discord(request: Request, user: User = Depends(current_user)):
    if not user.discorduser:
        return {'msg': 'Discord is not connected'}, HTTPStatus.BAD_REQUEST
    else:
        user.discord_user_id = None
        user.discord_user = None
        await async_session.commit()
        return JSONResponse({'disconnect': True})


@router.get('/callback')
async def callback(request: Request, error: Optional[str] = None, user: User = Depends(current_user)):
    if error:
        return error, HTTPStatus.INTERNAL_SERVER_ERROR
    discord = make_session(state=request.session.get('oauth2_state'), request=request)

    token = discord.fetch_token(
        TOKEN_URL,
        client_secret=OAUTH2_CLIENT_SECRET,
        authorization_response=str(request.url)
    )
    request.session['oauth2_token'] = token

    user_json = discord.get(API_BASE_URL + '/users/@me').json()

    discord_user = session.query(DiscordUser).filter_by(user_id=user_json['id']).first()
    new = False
    if not discord_user:
        new = True
        discord_user = DiscordUser(user_id=user_json['id'], user=user)

    discord_user.name = user_json['username']
    discord_user.avatar = user_json['avatar']

    user.discorduser = discord_user

    await async_session.commit()
    return RedirectResponse(url='/app/profile')
