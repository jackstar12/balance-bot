from client import Client


class BitmexClient(Client):
    exchange = 'bitmex'

    # https://www.bitmex.com/api/explorer/#!/User/User_getWallet
    def getBalance(self):
        # TODO: Implement Bitmex API
        raise NotImplementedError()
