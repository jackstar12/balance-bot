from tradealpha.common.models.async_websocket_manager import WebsocketManager


class KrakenWebsocketClient(WebsocketManager):
    def _get_url(self):
        pass

    async def _on_message(self, ws, message):
        pass