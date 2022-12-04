from enum import Enum
from typing import Type

from ccxt import Exchange

from common.exchanges.exchangeworker import ExchangeWorker
from database.models.client import ClientCreate
from common.exchanges.binance.worker import BinanceFutures, BinanceSpot
from common.exchanges.binance.ticker import BinanceFuturesTicker
from common.exchanges.bitmex.bitmex import BitmexWorker
from common.exchanges.bybit.derivatives import BybitDerivativesWorker
from common.exchanges.bybit.ticker import BybitDerivativesTicker
from common.exchanges.ftx.http import FtxWorker
from common.exchanges.ftx.ticker import FtxTicker
from common.exchanges.kucoin.kucoin import KuCoinFuturesWorker
from common.exchanges.okx.okx import OkxWorker
import ccxt


class ExchangeName(Enum):
    FTX = 'ftx'
    BINANCE_FUTURES = 'binance-futures'
    BYBIT = 'bybit'
    KUCOIN = 'kucoin'


EXCHANGES: dict[str, Type[ExchangeWorker]] = {
    worker.exchange: worker
    for worker in [
        BinanceFutures,
        BinanceSpot,
        BitmexWorker,
        FtxWorker,
        KuCoinFuturesWorker,
        BybitDerivativesWorker,
        OkxWorker,
    ]
}

EXCHANGE_TICKERS = {
    'ftx': FtxTicker,
    'binance-futures': BinanceFuturesTicker,
    'bybit-derivatives': BybitDerivativesTicker,
}

SANDBOX_CLIENTS = [
    ClientCreate(
        exchange=BinanceFutures.exchange,
        api_key="6ec9e23293ee07f187a8fbe4b575e6102da766daaa3e356db5d898ddfbb74684",
        api_secret="e9d2849343a017e466873810431b256bf13333ec257ead90618becb0f1a59ac6",
        sandbox=True
    ),
    ClientCreate(
        exchange=BybitDerivativesWorker.exchange,
        api_key="82UvSdVteZHLWMI9sm",
        api_secret="XA8mFgINADoMWLHxnOTVcRyubSGCGoJXQAyX",
        sandbox=True,
    ),
    ClientCreate(
        exchange=BinanceSpot.exchange,
        api_key="i4aHpzsGhRWFNyxf4JNrPm4AJEMrKYFMw0vhs9rk2AsIbIrAad2JwasIYkQA5krd",
        api_secret="FmD8pLQl3bsdc5xmYldUAKJWarr0wPxyARtY4sjpod3tSKBoycH3lvhNNw98E22S",
        sandbox=True
    )
]


MAINNET_CLIENTS = [
    ClientCreate(
        exchange=BinanceFutures.exchange,
        api_key="icMsTCEaI3hsB0CdtASDFiECGcndcSfBMqqVVfS2R9wawFHYW4qmTAF8HdAUCCEs",
        api_secret="hAuAsig9FJOKlCnwDhsxCnjUDq2a1JhQheuC4i2du7hRf6ol4clBOF9RPUkn4iEh",
        sandbox=False
    )
]


CCXT_CLIENTS: dict[str, Type[Exchange]] = {
    BinanceFutures.exchange: ccxt.binanceusdm,
    BinanceSpot.exchange: ccxt.binance,
    FtxWorker.exchange: ccxt.ftx,
    BitmexWorker.exchange: ccxt.bitmex,
    KuCoinFuturesWorker.exchange: ccxt.kucoin,
    OkxWorker.exchange: ccxt.okex,
    BybitDerivativesWorker.exchange: ccxt.bybit,
}

__all__ = [
    "binance",
    "bitmex",
    "bybit",
    "ftx",
    "kucoin",
    "okx",
    "EXCHANGES",
    "EXCHANGE_TICKERS",
    "SANDBOX_CLIENTS"
]
