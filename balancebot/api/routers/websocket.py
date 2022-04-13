import logging
from datetime import datetime
from http import HTTPStatus
from typing import Optional, Dict
from fastapi import APIRouter, Depends, Request, Response, WebSocket
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocketDisconnect

from balancebot.api.models.websocket import WebsocketMessage, WebsocketConfig
from balancebot.api.dependencies import current_user
from balancebot.api.dbmodels.client import Client
from balancebot.api.dbmodels.user import User
from balancebot.api.utils.client import create_cilent_data_serialized, get_user_client
import balancebot.api.utils.client as client_utils
from balancebot.common.messenger import Messenger, Category, SubCategory

from balancebot.collector.usermanager import UserManager


router = APIRouter(
    tags=["websocket"],
    dependencies=[Depends(current_user)],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


def create_ws_message(type: str, channel: str = None, data: Dict = None, error: str = None, *args):
    return {
        "type": type,
        "channel": channel,
        "data": data,
        "error": error
    }



@router.websocket('/client/ws')
async def client_websocket(websocket: WebSocket, user: User = Depends(current_user)):
    await websocket.accept()

    user_manager = UserManager()
    subscribed_client: Optional[Client] = None
    config: Optional[WebsocketConfig] = None
    messenger = Messenger()

    async def send_client_snapshot(client: Client, type: str, channel: str):
        msg = jsonable_encoder(create_ws_message(
            type=type,
            channel=channel,
            data=await create_cilent_data_serialized(
                client,
                config
            )
        ))
        await websocket.send_json(msg)

    def unsub_client(client: Client):
        if client:
            messenger.unsub_channel(Category.BALANCE, sub=SubCategory.NEW, channel_id=client.id)
            messenger.unsub_channel(Category.TRADE, sub=SubCategory.NEW, channel_id=client.id)
            messenger.unsub_channel(Category.TRADE, sub=SubCategory.UPDATE, channel_id=client.id)
            messenger.unsub_channel(Category.TRADE, sub=SubCategory.UPNL, channel_id=client.id)

    async def update_client(old: Client, new: Client):

        unsub_client(old)
        await send_client_snapshot(new, type='intial', channel='client')

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
                    data=client_utils.update_client_data_balance(
                        await client_utils.get_cached_data(config),
                        subscribed_client,
                        config
                    )
                )
            )

        messenger.sub_channel(
            Category.BALANCE, sub=SubCategory.NEW, channel_id=new.id,
            callback=send_balance_update
        )

        messenger.sub_channel(
            Category.TRADE, sub=SubCategory.NEW, channel_id=new.id,
            callback=send_trade_update
        )

        messenger.sub_channel(
            Category.TRADE, sub=SubCategory.UPDATE, channel_id=new.id,
            callback=send_trade_update
        )

        messenger.sub_channel(
            Category.TRADE, sub=SubCategory.UPNL, channel_id=new.id,
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