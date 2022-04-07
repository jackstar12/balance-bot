import aiohttp


class ExchangeTicker:

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session

    def