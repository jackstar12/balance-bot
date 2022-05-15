from balancebot.common.models.async_websocket_manager import WebsocketManager
from typing import TYPE_CHECKING


class BybitWebsocketClient(WebsocketManager):
    def _get_url(self):
        return "wss://stream.bybit.com/realtime"

    async def _on_message(self, ws, message):
        pass
