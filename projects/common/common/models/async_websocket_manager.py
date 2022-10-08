import asyncio
import json
import logging
import time
from asyncio import Future
from typing import Callable, Optional, Any

import aiohttp
import typing_extensions

from aiohttp import WSMessage
from typing_extensions import Self

from common import customjson
from common import utils


class MissingMessageError(Exception):
    pass


class WebsocketManager:
    _CONNECT_TIMEOUT_S = 5

    # Note that the url is provided through a function because some exchanges
    # have authentication embedded into the url
    def __init__(self,
                 session: aiohttp.ClientSession,
                 get_url: Callable[..., str],
                 on_connect: Callable[[Self], None] = None,
                 ping_forever_seconds: int = None,
                 logger: logging.Logger = None):
        self._ws: aiohttp.ClientWebSocketResponse = None
        self._session = session
        self._get_url = get_url
        self._on_connect = on_connect
        self._ping_forever_seconds = ping_forever_seconds
        self._logger = logger.getChild('WS') if logger else logging.getLogger(__name__)

        self._waiting: dict[str, Future] = {}

    @classmethod
    def _generate_id(cls) -> int:
        return time.monotonic_ns()

    def _get_message_id(self, message: dict) -> Any:
        raise NotImplementedError()

    async def send(self, msg: str | bytes, msg_id: Any = None):
        await self.connect()

        if isinstance(msg, str):
            msg = msg.encode('')
        self._logger.info(f'SENDING: {msg} {self._ws.closed=}')
        await self._ws._writer.send(msg, binary=False)

        if msg_id:
            fut = asyncio.get_running_loop().create_future()
            self._waiting[msg_id] = fut

            try:
                return await asyncio.wait_for(fut, 5)
            except asyncio.exceptions.CancelledError:
                raise MissingMessageError()

    def send_json(self, data: dict, msg_id: Any = None):
        return self.send(customjson.dumps(data), msg_id=msg_id)

    async def close(self):
        if self.connected:
            await self._ws.close()
            self._ws = None

    async def reconnect(self) -> None:
        await self.close()
        await self.connect()

    async def connect(self):
        if self.connected:
            return
        asyncio.create_task(self._run())

        ts = time.time()
        while not self.connected:
            if time.time() - ts > self._CONNECT_TIMEOUT_S:
                self._logger.info('Timeout')
                self._ws = None
                break
            await asyncio.sleep(0.25)

    @property
    def connected(self):
        return self._ws and not self._ws.closed

    async def _run(self):
        url = self._get_url()
        self._logger.info(f'Connecting to {url}')
        async with self._session.ws_connect(url, autoping=True) as ws:
            self._ws = ws
            self._logger.info(f'Connected to {url}')
            asyncio.create_task(self._ping_forever())
            await utils.call_unknown_function(self._on_connect, self)
            async for msg in ws:
                msg: WSMessage

                if msg.type == aiohttp.WSMsgType.PING:
                    await ws.pong()
                    continue
                if msg.type == aiohttp.WSMsgType.PONG:
                    continue
                if msg.type == aiohttp.WSMsgType.TEXT:
                    message = customjson.loads(msg.data)
                    try:
                        msg_id = self._get_message_id(message)
                        waiter = self._waiting.get(msg_id)
                        if waiter:
                            waiter.set_result(message)
                    except NotImplementedError:
                        pass
                    await self._callback(self._on_message, ws, message)
                if msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.info(f'DISCONNECTED {self=}')
                    await self._callback(self._on_error, ws)
                    break
                if msg.type == aiohttp.WSMsgType.CLOSED:
                    self._logger.info(f'DISCONNECTED {self=}')
                    await self._callback(self._on_close, ws)
                    break

    async def ping(self):
        raise NotImplementedError()

    async def _ping_forever(self):
        if self._ping_forever_seconds:
            while self.connected:
                try:
                    await self.ping()
                except MissingMessageError:
                    await self.reconnect()
                    break
                await asyncio.sleep(self._ping_forever_seconds)

    async def _callback(self, f, ws, *args, **kwargs):
        if callable(f) and ws is self._ws:
            try:
                await f(ws, *args, **kwargs)
            except Exception:
                logging.exception('Error running websocket callback:')

    async def _on_close(self, ws):
        await self.reconnect()

    async def _on_error(self, ws, error):
        await self.reconnect()

    def _get_url(self):
        raise NotImplementedError()

    async def _on_message(self, ws, message):
        raise NotImplementedError()
