import dotenv
import uvicorn
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette_csrf import CSRFMiddleware

import tradealpha.api.routers.analytics as analytics
import tradealpha.api.routers.authentication as auth
import tradealpha.api.routers.client as client
import tradealpha.api.routers.discordauth as discord
import tradealpha.api.routers.journal as journal
import tradealpha.api.routers.label as label
import tradealpha.api.routers.template as template
import tradealpha.api.routers.user as user

import tradealpha.common.dbasync as aio_db
from tradealpha.api.utils.responses import OK
from tradealpha.api.db_session_middleware import DbSessionMiddleware
from tradealpha.api.dependencies import CurrentUser, CurrentUserDep
from tradealpha.api.models.user import UserInfo, UserRead, UserCreate
from tradealpha.api.settings import settings
from tradealpha.api.users import fastapi_users
from tradealpha.common.utils import setup_logger

app = FastAPI(
    docs_url='/api/v1/docs',
    openapi_url='/api/v1/openapi.json',
    title="TradeAlpha",
    description='Trade Analytics and Journaling platform',
    version="0.0.1",
    terms_of_service="http://example.com/terms/",
    contact={
        "name": "Deadpoolio the Amazing",
        "url": "http://x-force.example.com/contact/",
        "email": "dp@x-force.example.com",
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html",
    },
)

#app.add_middleware(SessionMiddleware, secret_key='SECRET')
#app.add_middleware(CSRFMiddleware, secret='SECRET', sensitive_cookies=[settings.session_cookie_name])
# app.add_midleware(DbSessionMiddleware)

app.include_router(fastapi_users.get_verify_router(UserRead), prefix='/api/v1')
app.include_router(fastapi_users.get_reset_password_router(), prefix='/api/v1')
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix='/api/v1')

for module in (
        discord,
        auth,
        client,
        label,
        analytics,
        journal,
        template,
        user
):
    app.include_router(module.router, prefix='/api/v1')


@app.on_event("startup")
async def on_start():
    setup_logger()


@app.route('/api/v1/connectivity')
async def connectivity(*_):
    return OK('OK')


def run():
    uvicorn.run(app, host='localhost', port=5000)


if __name__ == '__main__':
    run()
