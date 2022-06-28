import asyncio
import time
from asyncio import Future

from balancebot.common import customjson
from balancebot.common.models.async_websocket_manager import WebsocketManager


class KucoinWebsocket(WebsocketManager):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._waiting_ids: set[int] = set()
        self._ping_timeout: Future | None = None

    async def _ping_timeout_waiter(self):
        self._ping_timeout = asyncio.sleep(10)
        try:
            await self._ping_timeout
            await self.reconnect()
        except asyncio.CancelledError:
            pass

    def _generate_id(self) -> int:
        new = time.monotonic_ns()
        self._waiting_ids.add(new)
        return new

    async def send_message(self, type: str, **kwargs):
        return await self.send_json({
            "id": self._generate_id(),
            "type": type,
            **kwargs
        })

    async def ping(self):
        asyncio.create_task(self._ping_timeout_waiter())
        return await self.send_message("ping")

    async def subscribe(self, topic: str, private_channel: bool):
        return await self.send_message("subscribe", topic=topic, privateChannel=private_channel)

    async def unsubscribe(self, topic: str, private_channel: bool):
        return await self.send_message("unsubscribe", topic=topic, privateChannel=private_channel)

    def _on_message(self, ws, raw_message):
        message = customjson.loads(raw_message)
        msg_type = message["type"]
        msg_id = message["id"]
        self._waiting_ids.remove(int(msg_id))
        if msg_type == "pong":
            self._ping_timeout.cancel()
        if msg_type == "message":
            await


