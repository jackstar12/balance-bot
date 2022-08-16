import time
from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import ORJSONResponse, UJSONResponse
from starlette.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from tradealpha.api.models.client import get_query_params
from tradealpha.common.dbmodels.mixins.querymixin import QueryParams
from tradealpha.api.authenticator import Authenticator
from tradealpha.api.models.analytics import ClientAnalytics, Calculation
from tradealpha.api.models.websocket import ClientConfig
from tradealpha.api.utils.analytics import create_cilent_analytics
from tradealpha.api.utils.client import get_user_client, get_user_clients
from tradealpha.common.dbasync import db_select
from tradealpha.common.dbmodels.client import Client
from tradealpha.common.dbmodels.execution import Execution
from tradealpha.common.dbmodels.trade import Trade
from tradealpha.common.dbmodels.user import User
import bcrypt

from tradealpha.api.dependencies import get_authenticator, CurrentUserDep, CurrentUser
from tradealpha.api.users import fastapi_users
from tradealpha.api.utils.responses import OK, CustomJSONResponse
from tradealpha.common.enums import Filter

router = APIRouter(
    tags=["analytics"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


