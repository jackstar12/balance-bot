from client import Client


class BitmexClient(Client):
    exchange = 'bitmex'

    def getBalance(self):
        # TODO: Implement Bitmex API
        raise NotImplementedError()
