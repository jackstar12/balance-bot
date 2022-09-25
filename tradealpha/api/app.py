import os

import dotenv
import uvicorn
from fastapi import FastAPI, Depends, APIRouter
from sqlalchemy.orm import object_session
from starlette.middleware.sessions import SessionMiddleware
from starlette_csrf import CSRFMiddleware
from httpx_oauth.clients.discord import DiscordOAuth2
import tradealpha.api.routers.analytics as analytics
import tradealpha.api.routers.authentication as auth
import tradealpha.api.routers.client as client
import tradealpha.api.routers.discordauth as discordauth
import tradealpha.api.routers.discord as discord
import tradealpha.api.routers.journal as journal
import tradealpha.api.routers.label as label
import tradealpha.api.routers.template as template
import tradealpha.api.routers.user as user
import tradealpha.api.routers.event as event
import tradealpha.api.routers.test as test
import tradealpha.api.routers.trade as trade
import tradealpha.common.dbasync as aio_db
from tradealpha.api.dependencies import get_db, messenger
from tradealpha.common.dbmodels import Event, Client, EventScore
from tradealpha.common.messenger import TableNames
from tradealpha.api.utils.responses import OK
from tradealpha.api.db_session_middleware import DbSessionMiddleware
from tradealpha.api.models.user import UserInfo, UserRead, UserCreate
from tradealpha.api.settings import settings
from tradealpha.api.users import fastapi_users, auth_backend, CurrentUser
from tradealpha.common.utils import setup_logger

VERSION = 1
PREFIX = f'/api/v{VERSION}'

app = FastAPI(
    docs_url='/api/v1/docs',
    openapi_url='/api/v1/openapi.json',
    title="TradeAlpha",
    description='Trade Analytics and Journaling platform',
    version="0.0.1",
    terms_of_service="https://example.com/terms/",
    contact={
        "name": "Deadpoolio the Amazing",
        "url": "https://x-force.example.com/contact/",
        "email": "dp@x-force.example.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)

#app.add_middleware(SessionMiddleware, secret_key='SECRET')
# app.add_middleware(CSRFMiddleware, secret='SECRET', sensitive_cookies=[settings.session_cookie_name])
# app.add_midleware(DbSessionMiddleware)

OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID')
OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET')
OAUTH2_REDIRECT_URI = os.environ.get('DISCORD_AUTH_REDIRECT')

assert OAUTH2_CLIENT_SECRET
assert OAUTH2_CLIENT_ID
assert OAUTH2_REDIRECT_URI

app.include_router(fastapi_users.get_verify_router(UserRead), prefix=PREFIX)
app.include_router(fastapi_users.get_reset_password_router(), prefix=PREFIX)
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix=PREFIX)
app.include_router(fastapi_users.get_auth_router(backend=auth_backend), prefix=PREFIX)

discord_oauth = DiscordOAuth2(
    OAUTH2_CLIENT_ID, OAUTH2_CLIENT_SECRET, scopes=['identify', 'email', 'guilds']
)

app.include_router(
    fastapi_users.get_custom_oauth_router(
        discord_oauth,
        user_schema=UserRead,
        backend=auth_backend,
        state_secret="SECRET",
    ),
    prefix=PREFIX + '/oauth/discord'
)

app.include_router(
    fastapi_users.get_oauth_associate_router(
        discord_oauth,
        user_schema=UserRead,
        state_secret="SECRET",
    ),
    prefix=PREFIX + '/oauth/discord/associate'
)


for module in (
        discord,
        # auth,
        client,
        label,
        analytics,
        journal,
        template,
        user,
        event,
        test,
        trade
):
    app.include_router(module.router, prefix='/api/v1')



@app.on_event("startup")
async def on_start():
    setup_logger()
    messenger.listen_class(Event)
    messenger.listen_class(Client)
    messenger.listen_class(EventScore)



def run():
    uvicorn.run(app, host='localhost', port=5000)


if __name__ == '__main__':
    run()
