from typing import Optional, Dict
from fastapi import APIRouter, Depends, WebSocket
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from tradealpha.api.models.websocket import WebsocketMessage, ClientConfig
from tradealpha.api.users import CurrentUser
from tradealpha.common.dbmodels.client import Client
from tradealpha.common.dbmodels.user import User
from tradealpha.api.utils.client import create_client_data_serialized, get_user_client
import tradealpha.api.utils.client as client_utils
from tradealpha.common.messenger import Messenger, TableNames, Category


router = APIRouter(
    tags=["websocket"],
    dependencies=[Depends(CurrentUser)],
    responses={
        401: {"msg": "Wrong Email or Password"},
        400: {"msg": "Email is already used"}
    }
)


# def create_ws_message(type: str, channel: str = None, data: Dict = None, error: str = None, *args):
#     return {
#         "type": type,
#         "channel": channel,
#         "data": data,
#         "error": error
#     }
#
#
#@router.websocket('/client/ws')
#async def client_websocket(websocket: WebSocket, csrf_token: str = Query(...),
#                           authenticator: Authenticator = Depends(get_authenticator)):
#    await websocket.accept()
#
#    authenticator.verify_id()
#    subscribed_client: Optional[Client] = None
#    config: Optional[ClientConfig] = None
#    messenger = Messenger()
#
#    async def send_client_snapshot(client: Client, type: str, channel: str):
#        msg = jsonable_encoder(create_ws_message(
#            type=type,
#            channel=channel,
#            data=await create_client_data_serialized(
#                client,
#                config
#            )
#        ))
#        await websocket.send_json(msg)
#
#    def unsub_client(client: Client):
#        if client:
#            messenger.unsub_channel(NameSpace.BALANCE, sub=Category.NEW, channel_id=client.id)
#            messenger.unsub_channel(NameSpace.TRADE, sub=Category.NEW, channel_id=client.id)
#            messenger.unsub_channel(NameSpace.TRADE, sub=Category.UPDATE, channel_id=client.id)
#            messenger.unsub_channel(NameSpace.TRADE, sub=Category.UPNL, channel_id=client.id)
#
#    async def update_client(old: Client, new: Client):
#
#        unsub_client(old)
#        await send_client_snapshot(new, type='initial', channel='client')
#
#        async def send_json_message(json: Dict):
#            await websocket.send_json(
#                jsonable_encoder(json)
#            )
#
#        async def send_upnl_update(data: Dict):
#            await send_json_message(
#                create_ws_message(
#                    type='trade',
#                    channel='upnl',
#                    data=data
#                )
#            )
#
#        async def send_trade_update(trade: Dict):
#            await send_json_message(
#                create_ws_message(
#                    type='client',
#                    channel='update',
#                    data=client_utils.update_client_data_trades(
#                        await client_utils.get_cached_data(config),
#                        [trade],
#                        config
#                    )
#                )
#            )
#
#        async def send_balance_update(balance: Dict):
#            await send_json_message(
#                create_ws_message(
#                    type='client',
#                    channel='update',
#                    data=await client_utils.update_client_data_balance(
#                        await client_utils.get_cached_data(config),
#                        subscribed_client,
#                        config
#                    )
#                )
#            )
#
#        await messenger.sub_channel(
#            NameSpace.BALANCE, sub=Category.NEW, channel_id=new.id,
#            callback=send_balance_update
#        )
#
#        await messenger.sub_channel(
#            NameSpace.TRADE, sub=Category.NEW, channel_id=new.id,
#            callback=send_trade_update
#        )
#
#        await messenger.sub_channel(
#            NameSpace.TRADE, sub=Category.UPDATE, channel_id=new.id,
#            callback=send_trade_update
#        )
#
#        await messenger.sub_channel(
#            NameSpace.TRADE, sub=Category.UPNL, channel_id=new.id,
#            callback=send_upnl_update
#        )
#
#    while True:
#        try:
#            raw_msg = await websocket.receive_json()
#            msg = WebsocketMessage(**raw_msg)
#            print(msg)
#            if msg.type == 'ping':
#                await websocket.send_json(create_ws_message(type='pong'))
#            elif msg.type == 'subscribe':
#                id = msg.data.get('id')
#                new_client = await get_user_client(user, id)
#
#                if not new_client:
#                    await websocket.send_json(create_ws_message(
#                        type='error',
#                        error='Invalid Client ID'
#                    ))
#                else:
#                    await update_client(old=subscribed_client, new=new_client)
#                    subscribed_client = new_client
#
#            elif msg.type == 'update':
#                if msg.channel == 'config':
#                    config = ClientConfig(**msg.data)
#                    logging.info(config)
#                    new_client = await get_user_client(user, config.id)
#                    if not new_client:
#                        await websocket.send_json(create_ws_message(
#                            type='error',
#                            error='Invalid Client ID'
#                        ))
#                    else:
#                        config.id = new_client.id
#                        config.currency = config.currency or '$'
#                        await update_client(old=subscribed_client, new=new_client)
#                        subscribed_client = new_client
#        except ValidationError as e:
#            await websocket.send_json(create_ws_message(
#                type='error',
#                error=str(e)
#            ))
#        except WebSocketDisconnect:
#            unsub_client(subscribed_client)
#            break
