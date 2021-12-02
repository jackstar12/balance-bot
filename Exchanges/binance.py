from client import Client


class BinanceClient(Client):
    exchange = 'binance'

    def getBalance(self):
        # TODO: Implement Binance API
        raise NotImplementedError()

