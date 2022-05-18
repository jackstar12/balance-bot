from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from starlette.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from balancebot.api.authenticator import Authenticator
from balancebot.api.models.analytics import ClientAnalytics, Calculation
from balancebot.api.models.client import ClientQueryParams
from balancebot.api.models.websocket import ClientConfig
from balancebot.api.utils.analytics import create_cilent_analytics
from balancebot.api.utils.client import get_user_client
from balancebot.common.database_async import db_select
from balancebot.common.dbmodels.user import User
import bcrypt

from balancebot.api.dependencies import get_authenticator, CurrentUser
from balancebot.api.users import fastapi_users
from balancebot.api.utils.responses import OK
from balancebot.common.enums import Filter

router = APIRouter(
    tags=["analytics"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


@router.get('/analytics', response_model=ClientAnalytics)
async def get_analytics(client_params: ClientQueryParams = Depends(),
                  filters: Tuple[Filter, ...] = Query(default=(Filter.LABEL,)),
                  calculate: Calculation = Query(default=Calculation.PNL),
                  user: User = Depends(CurrentUser)):
    config = ClientConfig.construct(**client_params.__dict__)
    client = await get_user_client(user, config.id)

    return create_cilent_analytics(client, config, filters=filters, filter_calculation=calculate)
