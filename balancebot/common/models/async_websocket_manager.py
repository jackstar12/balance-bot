import asyncio
import json
import logging
import time
from threading import Thread, Lock
import aiohttp
import threading

import websockets
from aiohttp import WSMessage
from websocket import WebSocketApp


class WebsocketManager:
    _CONNECT_TIMEOUT_S = 5

    def __init__(self, session: aiohttp.ClientSession):
        self._ws = None
        self._session = session

    async def send(self, message):
        await self.connect()
        self._ws.send(message)

    async def send_json(self, data):
        if self._ws and not self._ws.closed:
            return await self._ws.send_json(data)

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
            self._ws = ws
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
