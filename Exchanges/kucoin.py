from client import Client


class KuCoinClient(Client):
    exchange = 'kucoin'

    # https://docs.kucoin.com/#get-account-balance-of-a-sub-account
    def getBalance(self):
        # TODO: Implement KuCoin API
        raise NotImplementedError()
