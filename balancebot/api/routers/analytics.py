import time
from typing import List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import ORJSONResponse, UJSONResponse
from starlette.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from balancebot.api.authenticator import Authenticator
from balancebot.api.models.analytics import ClientAnalytics, Calculation
from balancebot.api.models.client import ClientQueryParams
from balancebot.api.models.websocket import ClientConfig
from balancebot.api.utils.analytics import create_cilent_analytics
from balancebot.api.utils.client import get_user_client, get_user_clients
from balancebot.common.dbasync import db_select
from balancebot.common.dbmodels.client import Client
from balancebot.common.dbmodels.execution import Execution
from balancebot.common.dbmodels.trade import Trade
from balancebot.common.dbmodels.user import User
import bcrypt

from balancebot.api.dependencies import get_authenticator, CurrentUserDep, CurrentUser
from balancebot.api.users import fastapi_users
from balancebot.api.utils.responses import OK, CustomJSONResponse
from balancebot.common.enums import Filter

router = APIRouter(
    tags=["analytics"],
    dependencies=[],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


@router.get('/trades-detailed', response_model=ClientAnalytics)
async def get_analytics(client_params: ClientQueryParams = Depends(),
                        filters: Tuple[Filter, ...] = Query(default=(Filter.LABEL,)),
                        calculate: Calculation = Query(default=Calculation.PNL),
                        user: User = Depends(CurrentUser)):
    config = ClientConfig.construct(**client_params.__dict__)
    clients = await get_user_clients(user,
                                     config.ids,
                                     (Client.trades, [
                                         Trade.executions,
                                         Trade.pnl_data,
                                         Trade.initial,
                                         Trade.max_pnl,
                                         Trade.min_pnl
                                     ]))

    response = [
        (await create_cilent_analytics(client, config, filters=filters, filter_calculation=calculate)).dict()
        for client in clients
    ]

    return CustomJSONResponse(
        content=jsonable_encoder(response)
    )
