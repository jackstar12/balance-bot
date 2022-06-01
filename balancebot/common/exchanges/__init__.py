from balancebot.common.exchanges.binance.binance import BinanceFutures, BinanceSpot
from balancebot.common.exchanges.binance.ticker import BinanceFuturesTicker
from balancebot.common.exchanges.bitmex.bitmex import BitmexClient
from balancebot.common.exchanges.bybit.bybit import BybitDerivativesClient
from balancebot.common.exchanges.bybit.ticker import BybitTicker
from balancebot.common.exchanges.ftx.http import FtxClient
from balancebot.common.exchanges.ftx.ticker import FtxTicker
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


EXCHANGE_TICKERS = {
    'ftx': FtxTicker,
    'binance-futures': BinanceFuturesTicker,
    'bybit-derivatives': BybitTicker
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
