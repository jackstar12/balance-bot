import asyncio
import json
import logging
import time
from typing import Callable

import aiohttp
import typing_extensions

from aiohttp import WSMessage
from typing_extensions import Self

from tradealpha.common import utils, customjson


class WebsocketManager:
    _CONNECT_TIMEOUT_S = 5

    # Note that the url is provided through a function because some exchanges
    # have authentication embedded into the url
    def __init__(self, session: aiohttp.ClientSession,
                 get_url: Callable[..., str],
                 on_message: Callable[[Self, str], None] = None,
                 on_connect: Callable[[Self], None] = None,
                 ping_forever_seconds: int = None):
        self._ws = None
        self._session = session
        self._get_url = get_url
        if on_message:
            self._on_message = on_message
        self._on_connect = on_connect
        self._ping_forever_seconds = ping_forever_seconds

    async def send(self, message):
        await self.connect()
        self._ws.send(message)

    async def send_json(self, data):
        if not self._ws or self._ws.closed:
            await self.connect()
        return await self._ws.send_json(data, dumps=customjson.dumps_no_bytes)

    async def reconnect(self) -> None:
        if self.connected:
            await self._ws.close()
            self._ws = None
        await self.connect()

    async def connect(self):
        if self.connected:
            return
        asyncio.create_task(self._run())

        ts = time.time()
        while not self.connected:
            if time.time() - ts > self._CONNECT_TIMEOUT_S:
                self._ws = None
                break
            await asyncio.sleep(0.1)

    @property
    def connected(self):
        return self._ws and not self._ws.closed

    async def _run(self):
        async with self._session.ws_connect(self._get_url(), autoping=True) as ws:
            asyncio.create_task(self._ping_forever())
            await utils.call_unknown_function(self._on_connect, self)
            self._ws: aiohttp.ClientWebSocketResponse = ws
            async for msg in ws:
                msg: WSMessage = msg  # Pycharm is a bit stupid sometimes.
                if msg.type == aiohttp.WSMsgType.PING:
                    await ws.pong()
                    continue
                if msg.type == aiohttp.WSMsgType.PONG:
                    continue
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self._callback(self._on_message, ws, msg.data)
                if msg.type == aiohttp.WSMsgType.ERROR:
                    logging.info(f'DISCONNECTED {self=}')
                    await self._callback(self._on_error, ws)
                    break
                if msg.type == aiohttp.WSMsgType.CLOSED:
                    logging.info(f'DISCONNECTED {self=}')
                    await self._callback(self._on_close, ws)
                    break

    async def ping(self):
        raise NotImplementedError()

    async def _ping_forever(self):
        if self._ping_forever_seconds:
            while self.connected:
                await self.ping()
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
