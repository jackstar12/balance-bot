from client import Client
import requests


class FtxClient(Client):
    exchange = 'ftx'
    _ENDPOINT = 'https://ftx.com/api/'

    def getBalance(self):
        # TODO: Implement FTX API
        raise NotImplementedError()