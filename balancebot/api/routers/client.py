import logging
from datetime import datetime
from http import HTTPStatus
from typing import Optional, Dict
import aiohttp
import jwt
from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy import or_
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from balancebot import utils
from balancebot.api.dependencies import current_user
from balancebot.api.database import session
from balancebot.api.dbmodels.client import Client, get_client_query
from balancebot.api.dbmodels.user import User
from balancebot.api.settings import settings

from balancebot.exchangeworker import ExchangeWorker
from balancebot.bot.config import EXCHANGES

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
               id: Optional[int] = None, currency: Optional[str] = None, since: Optional[datetime] = None, to: Optional[datetime] = None,
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
            to_date = now
        else:
            to_date = datetime.fromtimestamp(int(to))

        if not since:
            since_date = datetime.fromtimestamp(0)
            since = '0'
        else:
            since_date = datetime.fromtimestamp(int(since))

        last_fetch = datetime.fromtimestamp(float(request.cookies.get('client-last-fetch', 0)))
        latest_balance = client.history[len(client.history) - 1] if client.history else None

        if tf_update or (latest_balance and latest_balance.time > last_fetch < to_date):
            s = client.serialize(full=True, data=False)

            history = []
            s['daily'] = utils.calc_daily(
                client=client,
                forEach=lambda balance: history.append(balance.serialize(full=True, data=True, currency=currency)),
                throw_exceptions=False,
                since=since_date,
                to=to_date
            )
            s['history'] = history

            def ratio(a: float, b: float):
                return round(a / (a + b), ndigits=3) if a + b > 0 else 0.5

            winning_days, losing_days = 0, 0
            for day in s['daily']:
                if day[2] > 0:
                    winning_days += 1
                elif day[2] < 0:
                    losing_days += 1

            s['daily_win_ratio'] = ratio(winning_days, losing_days)
            s['winning_days'] = winning_days
            s['losing_days'] = losing_days

            trades = []
            winners, losers = 0, 0
            avg_win, avg_loss = 0.0, 0.0
            for trade in client.trades:
                if since_date <= trade.initial.time <= to_date:
                    trade = trade.serialize(data=True)
                    if trade['status'] == 'win':
                        winners += 1
                        avg_win += trade['realized_pnl']
                    elif trade['status'] == 'loss':
                        losers += 1
                        avg_loss += trade['realized_pnl']
                    trades.append(trade)

            s['trades'] = trades
            s['win_ratio'] = ratio(winners, losers)
            s['winners'] = winners
            s['losers'] = losers
            s['avg_win'] = avg_win / (winners or 1)
            s['avg_loss'] = avg_loss / (losers or 1)
            s['action'] = 'NEW'

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
    if id:
        client: Optional[Client] = get_client_query(user, id).first()
    elif len(user.clients) > 0:
        client: Optional[Client] = user.clients[0]
    elif user.discorduser:
        client: Optional[Client] = user.discorduser.global_client
    else:
        client = None
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
