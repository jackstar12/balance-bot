import os

import uvicorn
from fastapi import FastAPI, Depends, APIRouter, HTTPException
from httpx_oauth.clients.discord import DiscordOAuth2

import api.routers.action as action
import api.routers.analytics as analytics
import api.routers.client as client
import api.routers.discord as discord
import api.routers.event as event
import api.routers.journal as journal
import api.routers.label as label
import api.routers.template as template
import api.routers.test as test
import api.routers.trade as trade
import api.routers.user as user
from api.dependencies import messenger
from api.models.user import UserRead, UserCreate
from api.routers import labelgroup
from api.users import fastapi_users, auth_backend
from database.dbmodels import Event, Client, EventEntry
from core.utils import setup_logger

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

# app.add_middleware(SessionMiddleware, secret_key='SECRET')
# app.add_middleware(CSRFMiddleware, secret='SECRET', sensitive_cookies=[settings.session_cookie_name])
# app.add_midleware(DbSessionMiddleware)

OAUTH2_CLIENT_ID = os.environ.get('OAUTH2_CLIENT_ID')
OAUTH2_CLIENT_SECRET = os.environ.get('OAUTH2_CLIENT_SECRET')
OAUTH2_REDIRECT_URI = os.environ.get('REDIRECT_BASE_URI')

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

OAUTH_PREFIX = '/oauth/discord'

app.include_router(
    fastapi_users.get_custom_oauth_router(
        discord_oauth,
        user_schema=UserRead,
        backend=auth_backend,
        state_secret="SECRET",
        redirect_url=OAUTH2_REDIRECT_URI + OAUTH_PREFIX + '/callback'
    ),
    prefix=PREFIX + OAUTH_PREFIX
)


ASSOC_PREFIX = OAUTH_PREFIX + '/associate'

app.include_router(
    fastapi_users.get_oauth_associate_router(
        discord_oauth,
        user_schema=UserRead,
        state_secret="SECRET",
        redirect_url=OAUTH2_REDIRECT_URI + ASSOC_PREFIX + '/callback'
    ),
    prefix=PREFIX + ASSOC_PREFIX
)

for module in (
        # auth,
        discord,
        labelgroup,
        label,
        analytics,
        journal,
        template,
        user,
        event,
        test,
        trade,
        action,
        client,
):
    app.include_router(module.router, prefix='/api/v1')


db_permission_flag = False


def enforce_enabled():
    if not db_permission_flag:
        raise HTTPException(status_code=400, detail='Route is not enabled')


protected_router = APIRouter(
    dependencies=[Depends(enforce_enabled)]
)


@protected_router.get('/has-to-be-enabled')
async def some_route():
    pass


@protected_router.get('/also-to-be-enabled')
async def some_other_route():
    pass


@app.on_event("startup")
async def on_start():
    setup_logger()
    messenger.listen_class_all(Event)
    messenger.listen_class_all(Client)


def run():
    uvicorn.run(app, host='localhost', port=5000)


if __name__ == '__main__':
    run()
