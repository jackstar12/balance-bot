from balancebot.common.exchanges.binance.binance import BinanceFutures, BinanceSpot
from balancebot.common.exchanges.bitmex.bitmex import BitmexClient
from balancebot.common.exchanges.bybit.bybit import BybitDerivativesClient
from balancebot.common.exchanges.ftx.http import FtxClient
from balancebot.common.exchanges.kucoin.kucoin import KuCoinClient
from balancebot.common.exchanges.okx.okx import OkxClient


EXCHANGES = {
    'binance-futures': BinanceFutures,
    'binance-spot': BinanceSpot,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient,
    'bybit-derivatives': BybitDerivativesClient,
    'okx': OkxClient,
}


__all__ = [
    "binance",
    "bitmex",
    "bybit",
    "ftx",
    "kucoin",
    "okx",
    "EXCHANGES"
]
