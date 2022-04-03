import asyncio
import logging
from datetime import datetime
from http import HTTPStatus
from typing import Optional, Dict, Type
import aiohttp
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Response, WebSocket
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from sqlalchemy import or_
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from balancebot import utils
from balancebot.api.dbmodels.balance import Balance
from balancebot.api.dbmodels.serializer import Serializer
from balancebot.api.dbmodels.trade import Trade
from balancebot.api.dependencies import current_user
from balancebot.api.database import session
from balancebot.api.dbmodels.client import Client, get_client_query
from balancebot.api.dbmodels.user import User
from balancebot.api.settings import settings
from balancebot.api.utils.client import create_cilent_data_serialized, get_user_client

from balancebot.exchangeworker import ExchangeWorker
from balancebot.bot.config import EXCHANGES
from balancebot.usermanager import UserManager

router = APIRouter(
    tags=["client"],
    dependencies=[Depends(current_user)],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


class RegisterBody(BaseModel):
    exchange: str
    api_key: str
    api_secret: str
    subaccount: str
    kwargs: Dict


@router.post('/client')
async def register_client(body: RegisterBody):
    try:
        exchange_cls = EXCHANGES[body.exchange]
        if issubclass(exchange_cls, ExchangeWorker):
            # Check if required keyword args are given
            if len(body.kwargs.keys()) >= len(exchange_cls.required_extra_args) and \
                    all(required_kwarg in body.kwargs for required_kwarg in exchange_cls.required_extra_args):
                client = Client(
                    api_key=body.api_key,
                    api_secret=body.api_secret,
                    subaccount=body.subaccount,
                    extra_kwargs=body.kwargs,
                    exchange=body.exchange
                )
                async with aiohttp.ClientSession as http_session:
                    worker = exchange_cls(client, http_session)
                    init_balance = await worker.get_balance(datetime.now())
                if init_balance.error is None:
                    if round(init_balance.amount, ndigits=2) == 0.0:
                        return {
                            'msg': f'You do not have any balance in your account. Please fund your account before registering.'}
                    else:
                        payload = client.serialize(full=True, data=True)
                        # TODO: CHANGE THIS
                        payload['api_secret'] = client.api_secret
                        return {
                                   'msg': 'Success',
                                   'token': jwt.encode(payload, settings.authjwt_secret_key, algorithm='HS256'),
                                   'balance': init_balance.amount
                               }, HTTPStatus.OK
                else:
                    return {
                               'msg': f'An error occured while getting your balance: {init_balance.error}.'}, HTTPStatus.BAD_REQUEST
            else:
                logging.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.\nGot: {kwargs}\nRequired: {exchange_cls.required_extra_args}')
                args_readable = '\n'.join(exchange_cls.required_extra_args)
                return {
                           'msg': f'Need more keyword arguments for exchange {exchange_cls.exchange}.\nRequirements:\n {args_readable}',
                           'code': 40100
                       }, HTTPStatus.BAD_REQUEST

        else:
            logging.error(f'Class {exchange_cls} is no subclass of ClientWorker!')
    except KeyError:
        return {'msg': f'Exchange {body.exchange} unknown'}, HTTPStatus.BAD_REQUEST


@router.get('/client')
def get_client(request: Request, response: Response,
               id: Optional[int] = None, currency: Optional[str] = None, since: Optional[datetime] = None,
               to: Optional[datetime] = None,
               user: User = Depends(current_user)):
    if not currency:
        currency = '$'

    if id:
        client: Optional[Client] = get_client_query(user, id).first()
    elif len(user.clients) > 0:
        client: Optional[Client] = user.clients[0]
    elif user.discorduser:
        client: Optional[Client] = user.discorduser.global_client
    else:
        client = None
    if client:

        # Has selected timeframe changed?
        # tf_update = since != request.cookies.get('client-since') or to != request.cookies.get('client-to')
        tf_update = True

        now = datetime.now()

        if not to:
            to = now

        if not since:
            since = datetime.fromtimestamp(0)

        to = to.replace(tzinfo=pytz.UTC)
        since = since.replace(tzinfo=pytz.UTC)

        last_fetch = datetime.fromtimestamp(float(request.cookies.get('client-last-fetch', 0)))
        latest_balance = client.history[len(client.history) - 1] if client.history else None

        if tf_update or (latest_balance and latest_balance.time > last_fetch < to):
            s = create_cilent_data_serialized(client, since_date=since, to_date=to)

            response = JSONResponse(jsonable_encoder(s))
            response.set_cookie('client-last-fetch', value=str(now.timestamp()))
            # response.set_cookie('client-since', value=since, expires='session')
            # response.set_cookie('client-to', value=to, expires='session')

            return response
        else:
            return JSONResponse(
                {'msg': 'No changes', 'code': 20000},
                status_code=HTTPStatus.OK
            )
    else:
        return JSONResponse(
            {'msg': f'Invalid client id', 'code': 40000},
            status_code=HTTPStatus.BAD_REQUEST
        )


def get_client_analytics(id: Optional[int] = None, since: Optional[datetime] = None, to: Optional[datetime] = None,
                         user: User = Depends(current_user)):
    client = get_user_client(user, id)
    if client:

        resp = {}

        trades = []
        winners, losers = 0, 0
        avg_win, avg_loss = 0.0, 0.0
        for trade in client.trades:
            if since <= trade.initial.time <= to:
                trade = trade.serialize(data=True)
                if trade['status'] == 'win':
                    winners += 1
                    avg_win += trade['realized_pnl']
                elif trade['status'] == 'loss':
                    losers += 1
                    avg_loss += trade['realized_pnl']
                trades.append(trade)

        label_performance = {}
        for label in user.labels:
            for trade in label.trades:
                if not trade.open_qty:
                    label_performance[label.id] += trade.realized_pnl

        daily = utils.calc_daily(client)

        weekday_performance = [0] * 7
        for day in daily:
            weekday_performance[day.day.weekday()] += day.diff_absolute

        weekday_performance = []
        intraday_performance = []
        for trade in client.trades:
            weekday_performance[trade.initial.time.weekday()] += trade.realized_pnl

        return {
            'label_performance': label_performance,
            'weekday_performance': weekday_performance
        }


class DeleteBody(BaseModel):
    id: int


@router.delete('/client')
def delete_client(body: DeleteBody, user: User = Depends(current_user)):
    get_client_query(user, body.id).delete()
    session.commit()
    return {'msg': 'Success'}, HTTPStatus.OK


class ConfirmBody(BaseModel):
    token: str


@router.post('/client/confirm')
def confirm_client(body: ConfirmBody, user: User = Depends(current_user)):
    client_json = jwt.decode(body.token, settings.authjwt_secret_key, algorithms=['HS256'])
    print(client_json)
    try:
        client = Client(**client_json)
        user.clients.append(client)
        session.add(client)
        session.commit()
        return {'msg': 'Success'}, HTTPStatus.OK
    except TypeError:
        return {'msg': 'Internal Error'}, HTTPStatus.INTERNAL_SERVER_ERROR


def create_ws_message(type: str, channel: str = None, data: Dict = None, error: str = None, *args):
    return {
        "type": type,
        "channel": channel,
        "data": data,
        "error": error
    }


class WebsocketMessage(BaseModel):
    type: str
    channel: Optional[str]
    data: Optional[Dict]


class WebsocketConfig(BaseModel):
    id: Optional[int]
    since: Optional[datetime]
    to: Optional[datetime]
    currency: Optional[str]


@router.websocket('/client/ws')
async def client_websocket(websocket: WebSocket, user: User = Depends(current_user)):
    await websocket.accept()

    user_manager = UserManager()
    subscribed_client: Optional[Client] = None
    config: Optional[WebsocketConfig] = None

    async def send_client_snapshot(client: Client):
        msg = jsonable_encoder(create_ws_message(
            type='initial',
            channel='client',
            data=create_cilent_data_serialized(
                client,
                since_date=config.since,
                to_date=config.to,
                currency=config.currency
            )
        ))
        await websocket.send_json(msg)

    def websocket_callback(type: str, channel: str):
        async def f(worker: ExchangeWorker, obj: Serializer):
            await websocket.send_json(create_ws_message(
                type=type,
                channel=channel,
                data=jsonable_encoder(obj.serialize())
            ))

        return f

    async def update_client(old: Client, new: Client):

        if old:
            old_worker: ExchangeWorker = user_manager.get_worker(old)
            if old_worker:
                old_worker.clear_callbacks()

        await send_client_snapshot(new)
        worker = user_manager.get_worker(new)

        worker.set_balance_callback(
            websocket_callback(type='new', channel='balance')
        )
        worker.set_trade_callback(
            websocket_callback(type='new', channel='trade')
        )
        worker.set_trade_update_callback(
            websocket_callback(type='update', channel='trade')
        )

    while True:
        raw_msg = await websocket.receive_json()
        try:
            msg = WebsocketMessage(**raw_msg)
            print(msg)
            if msg.type == 'ping':
                await websocket.send_json(create_ws_message(type='pong'))
            elif msg.type == 'subscribe':
                id = msg.data.get('id')
                new_client = get_user_client(user, id)

                if not new_client:
                    await websocket.send_json(create_ws_message(
                        type='error',
                        error='Invalid Client ID'
                    ))
                else:
                    await update_client(old=subscribed_client, new=new_client)
                    subscribed_client = new_client

            elif msg.type == 'update':
                if msg.channel == 'config':
                    config = WebsocketConfig(**msg.data)
                    new_client = get_user_client(user, config.id)
                    if not new_client:
                        await websocket.send_json(create_ws_message(
                            type='error',
                            error='Invalid Client ID'
                        ))
                    else:
                        await update_client(old=subscribed_client, new=new_client)
                        subscribed_client = new_client
        except ValidationError as e:
            await websocket.send_json(create_ws_message(
                type='error',
                error=str(e)
            ))
