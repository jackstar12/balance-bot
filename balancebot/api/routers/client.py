import logging
from datetime import datetime
from http import HTTPStatus
from typing import Optional, Dict, List
import aiohttp
import jwt
import pytz
from fastapi import APIRouter, Depends, Request, Response, WebSocket, Query
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import or_, delete, select, update
from starlette.responses import JSONResponse
from starlette.websockets import WebSocketDisconnect

from balancebot.api.authenticator import Authenticator
from balancebot.api.models.analytics import ClientAnalytics, FilteredPerformance
from balancebot.common.database_async import db, db_first, async_session, db_all, db_select
from balancebot.common.dbmodels.guildassociation import GuildAssociation
from balancebot.common.dbmodels.guild import Guild
from balancebot.api.models.client import RegisterBody, DeleteBody, ConfirmBody, UpdateBody, ClientQueryParams
from balancebot.api.models.websocket import WebsocketMessage, ClientConfig
from balancebot.api.utils.responses import BadRequest, OK, CustomJSONResponse
from balancebot.common import utils
from balancebot.api.dependencies import current_user, CurrentUser, get_authenticator
from balancebot.common.database import session
from balancebot.common.dbmodels.client import Client, add_client_filters
from balancebot.common.dbmodels.user import User
from balancebot.api.settings import settings
from balancebot.api.utils.client import create_client_data_serialized, get_user_client
import balancebot.api.utils.client as client_utils
from balancebot.common.messenger import Messenger, NameSpace, Category
import balancebot.common.dbmodels.event as db_event
from balancebot.common.utils import validate_kwargs

from balancebot.common.exchanges.exchangeworker import ExchangeWorker
from balancebot.common.exchanges import EXCHANGES
from balancebot.collector.usermanager import UserManager

router = APIRouter(
    tags=["client"],
    dependencies=[Depends(current_user)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


@router.post('/client')
async def register_client(request: Request, body: RegisterBody, authenticator: Authenticator = Depends(get_authenticator)):
    await authenticator.read_uuid(request)
    try:
        exchange_cls = EXCHANGES[body.exchange]
        if issubclass(exchange_cls, ExchangeWorker):
            # Check if required keyword args are given
            if validate_kwargs(body.extra or {}, exchange_cls.required_extra_args):
                client = Client(
                    name=body.name,
                    api_key=body.api_key,
                    api_secret=body.api_secret,
                    subaccount=body.subaccount,
                    extra_kwargs=body.extra,
                    exchange=body.exchange
                )
                async with aiohttp.ClientSession() as http_session:
                    worker = exchange_cls(client, http_session)
                    init_balance = await worker.get_balance(date=datetime.now(pytz.utc))
                if init_balance.error is None:
                    if init_balance.realized.is_zero():
                        return BadRequest(
                            f'You do not have any balance in your account. Please fund your account before registering.'
                        )
                    else:
                        payload = await  client.serialize(full=True, data=True)
                        # TODO: CHANGE THIS
                        payload['api_secret'] = client.api_secret

                        return JSONResponse(jsonable_encoder({
                            'msg': 'Success',
                            'token': jwt.encode(payload, settings.authjwt_secret_key, algorithm='HS256'),
                            'balance': init_balance.serialize()
                        }))
                else:
                    return BadRequest(f'An error occured while getting your balance: {init_balance.error}.')
            else:
                logging.error(
                    f'Not enough kwargs for exchange {exchange_cls.exchange} were given.'
                    f'\nGot: {body.extra}\nRequired: {exchange_cls.required_extra_args}'
                )
                args_readable = '\n'.join(exchange_cls.required_extra_args)
                return BadRequest(
                    detail=f'Need more keyword arguments for exchange {exchange_cls.exchange}.'
                        f'\nRequirements:\n {args_readable}',
                    code=40100
                )

        else:
            logging.error(f'Class {exchange_cls} is no subclass of ClientWorker!')
    except KeyError:
        return BadRequest(f'Exchange {body.exchange} unknown')


@router.get('/client')
async def get_client(request: Request, response: Response,
                     client_params: ClientQueryParams = Depends(),
                     user: User = Depends(current_user)):

    if client_params.id:
        client: Optional[Client] = await db_first(
            add_client_filters(select(Client), user, client_params.id)
        )
    else:
        client: Optional[Client] = await db_select(Client, eager=[(Client.trades, "*")], user_id=user.id)
        if not client:
            client: Optional[Client] = await db_select(Client, eager=[(Client.trades, "*")], discord_user_id=user.discord_user_id)

    if client:
        s = await create_client_data_serialized(client,
                                                ClientConfig.construct(**client_params.__dict__))
        encoded = jsonable_encoder(s)
        response = CustomJSONResponse(encoded)
        # response.set_cookie('client-since', value=since, expires='session')
        # response.set_cookie('client-to', value=to, expires='session')
        return response
    else:
        return BadRequest('Invalid client id', 40000)


async def get_client_analytics(id: Optional[int] = None, since: Optional[datetime] = None,
                               to: Optional[datetime] = None,
                               user: User = Depends(current_user)):
    client = await get_user_client(user, id)
    if client:

        resp = {}

        trades = []
        winners, losers = 0, 0
        avg_win, avg_loss = 0.0, 0.0
        for trade in client.trades:
            if since <= trade.initial.time <= to:
                trade = await trade.serialize(data=True)
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

        daily = await utils.calc_daily(client)

        weekday_performance = [0] * 7
        for day in daily:
            weekday_performance[day.day.weekday()] += day.diff_absolute

        weekday_performance = []
        intraday_performance = []
        for trade in client.trades:
            weekday_performance[trade.initial.time.weekday()] += trade.realized_pnl

        return ClientAnalytics(
            id=client.id,
            filtered_performance=FilteredPerformance(

            )
        )

        return {
            'label_performance': label_performance,
            'weekday_performance': weekday_performance
        }


@router.delete('/client')
async def delete_client(body: DeleteBody, user: User = Depends(current_user)):
    await db(
        add_client_filters(delete(Client), user, body.id)
    )
    await async_session.commit()
    return OK(detail='Success')


@router.patch('/client')
async def update_client(body: UpdateBody, user: User = Depends(CurrentUser(User.discord_user))):
    client: Client = await db_first(
        add_client_filters(select(Client), user, body.id)
    )

    if body.archived is not None:
        client.archived = body.archived

    # Check explicitly for False and True because we don't want to do anything on None
    if body.discord is False:
        client.discord_user_id = None
        client.user_id = user.id
        await db(
            update(GuildAssociation).where(
                GuildAssociation.client_id == client.id
            ).values(client_id=None)
        )

    elif body.discord is True:
        if user.discord_user_id:
            client.discord_user_id = user.discord_user_id
            client.user_id = None
            if body.servers is not None:

                if body.servers:
                    await db(
                        update(GuildAssociation).where(
                            GuildAssociation.discord_user_id == user.discord_user_id,
                            GuildAssociation.guild_id.in_(body.servers)
                        ).values(client_id=client.id)
                    )

                #await db(
                #    update(GuildAssociation).where(
                #        GuildAssociation.discord_user_id == user.discord_user_id,
                #        GuildAssociation.guild_id.not_in(body.servers)
                #    ).values(client_id=None)
                #)

                #guilds: List[Guild] = await db_all(
                #    select(Guild).filter(
                #        or_(*[Guild.id == guild_id for guild_id in body.servers]),
                #    ),
                #    Guild.users
                #)
                #for guild in guilds:
                #    if user.discord_user in guild.users:
                #        guild.global_clients.append(
                #            GuildAssociation(
                #                discord_user_id=user.discord_user_id,
                #                client_id=client.id
                #            )
                #        )
                #    else:
                #        return BadRequest(f'You are not eligible to register in guild {guild.name}')
                await async_session.commit()
            if body.events is not None:
                now = datetime.now(tz=pytz.UTC)
                events = session.query(db_event.Event).filter(
                    or_(*[db_event.Event.id == event_id for event_id in body.events])
                ).all()
                valid_events = []
                for event in events:
                    if event.is_free_for_registration(now):
                        if event.guild in user.discord_user.guilds:
                            valid_events.append(event)
                        else:
                            return BadRequest(f'You are not eligible to join {event.name} (Not in server)')
                    else:
                        return BadRequest(f'Event {event.name} is not free for registration')
                if valid_events:
                    for valid in valid_events:
                        client.events.append(valid)
                else:
                    return BadRequest('No valid events were provided')

            if body.servers is None and body.events is None:
                return BadRequest('Either servers or events have to be provided')
        else:
            return BadRequest('No discord account found')

        await async_session.commit()
        return OK('Changes applied')


@router.post('/client/confirm')
async def confirm_client(body: ConfirmBody, user: User = Depends(current_user)):
    client_json = jwt.decode(body.token, settings.authjwt_secret_key, algorithms=['HS256'])
    print(client_json)
    try:
        client = Client(**client_json)
        client.user = user
        async_session.add(client)
        await async_session.commit()
        return OK('Success')
    except TypeError:
        return BadRequest(detail='Invalid token')


def create_ws_message(type: str, channel: str = None, data: Dict = None, error: str = None, *args):
    return {
        "type": type,
        "channel": channel,
        "data": data,
        "error": error
    }


@router.websocket('/client/ws')
async def client_websocket(websocket: WebSocket, csrf_token: str = Query(...),  authenticator: Authenticator = Depends(get_authenticator)):
    await websocket.accept()
    Authorize.jwt_required("websocket", websocket)
    user_manager = UserManager()
    subscribed_client: Optional[Client] = None
    config: Optional[ClientConfig] = None
    messenger = Messenger()

    async def send_client_snapshot(client: Client, type: str, channel: str):
        msg = jsonable_encoder(create_ws_message(
            type=type,
            channel=channel,
            data=await create_client_data_serialized(
                client,
                config
            )
        ))
        await websocket.send_json(msg)

    def unsub_client(client: Client):
        if client:
            messenger.unsub_channel(NameSpace.BALANCE, sub=Category.NEW, channel_id=client.id)
            messenger.unsub_channel(NameSpace.TRADE, sub=Category.NEW, channel_id=client.id)
            messenger.unsub_channel(NameSpace.TRADE, sub=Category.UPDATE, channel_id=client.id)
            messenger.unsub_channel(NameSpace.TRADE, sub=Category.UPNL, channel_id=client.id)

    async def update_client(old: Client, new: Client):

        unsub_client(old)
        await send_client_snapshot(new, type='initial', channel='client')

        async def send_json_message(json: Dict):
            await websocket.send_json(
                jsonable_encoder(json)
            )

        async def send_upnl_update(data: Dict):
            await send_json_message(
                create_ws_message(
                    type='trade',
                    channel='upnl',
                    data=data
                )
            )

        async def send_trade_update(trade: Dict):
            await send_json_message(
                create_ws_message(
                    type='client',
                    channel='update',
                    data=client_utils.update_client_data_trades(
                        await client_utils.get_cached_data(config),
                        [trade],
                        config
                    )
                )
            )

        async def send_balance_update(balance: Dict):
            await send_json_message(
                create_ws_message(
                    type='client',
                    channel='update',
                    data=await client_utils.update_client_data_balance(
                        await client_utils.get_cached_data(config),
                        subscribed_client,
                        config
                    )
                )
            )

        messenger.sub_channel(
            NameSpace.BALANCE, sub=Category.NEW, channel_id=new.id,
            callback=send_balance_update
        )

        messenger.sub_channel(
            NameSpace.TRADE, sub=Category.NEW, channel_id=new.id,
            callback=send_trade_update
        )

        messenger.sub_channel(
            NameSpace.TRADE, sub=Category.UPDATE, channel_id=new.id,
            callback=send_trade_update
        )

        messenger.sub_channel(
            NameSpace.TRADE, sub=Category.UPNL, channel_id=new.id,
            callback=send_upnl_update
        )

    while True:
        try:
            raw_msg = await websocket.receive_json()
            msg = WebsocketMessage(**raw_msg)
            print(msg)
            if msg.type == 'ping':
                await websocket.send_json(create_ws_message(type='pong'))
            elif msg.type == 'subscribe':
                id = msg.data.get('id')
                new_client = await get_user_client(user, id)

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
                    config = ClientConfig(**msg.data)
                    logging.info(config)
                    new_client = await get_user_client(user, config.id)
                    if not new_client:
                        await websocket.send_json(create_ws_message(
                            type='error',
                            error='Invalid Client ID'
                        ))
                    else:
                        config.id = new_client.id
                        config.currency = config.currency or '$'
                        await update_client(old=subscribed_client, new=new_client)
                        subscribed_client = new_client
        except ValidationError as e:
            await websocket.send_json(create_ws_message(
                type='error',
                error=str(e)
            ))
        except WebSocketDisconnect:
            unsub_client(subscribed_client)
            break
