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
        self.connect_lock = Lock()
        self._ws = None
        self._session = session

    def send(self, message):
        self.connect()
        self._ws.send(message)

    async def send_json(self, data):
        if self._ws and not self._ws.closed:
            return await self._ws.send_json(data)

    def reconnect(self) -> None:
        if self.connected:
            self._reconnect(self._ws)

    def connect(self):
        if self.connected:
            return
        asyncio.create_task(self._async_connect())

    @property
    def connected(self):
        return self._ws and not self._ws.closed

    async def _async_connect(self):
        async with self._session.ws_connect(self._get_url(), autoping=True) as ws:
            self._ws = ws
            async for msg in ws:
                msg: WSMessage = msg  # Pycharm is a bit stupid sometimes.
                print('Message received from server:', msg)
                print(msg.json())
                if msg.type == aiohttp.WSMsgType.PING:
                    await ws.pong()
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    self._callback(self._on_message, ws, msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._callback(self._on_close, ws)
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    self._callback(self._on_close, ws)
                    break

    def _callback(self, f, ws, *args, **kwargs):
        if callable(f) and ws is self._ws:
            try:
                f(ws, *args, **kwargs)
            except Exception:
                logging.exception('Error running websocket callback:')

    def _run_websocket(self, ws):
        try:
            ws.run_forever()
        except Exception as e:
            raise Exception(f'Unexpected error while running websocket: {e}')
        finally:
            self._reconnect(ws)

    async def _reconnect(self, ws):
        assert ws is not None, '_reconnect should only be called with an existing ws'
        if ws is self._ws:
            self._ws = None
            await ws.close()
            self.connect()

    def _on_close(self, ws):
        self._reconnect(ws)

    def _on_error(self, ws, error):
        self._reconnect(ws)

    def _get_url(self):
        raise NotImplementedError()

    def _on_message(self, ws, message):
        raise NotImplementedError()
