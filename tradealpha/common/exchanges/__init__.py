from tradealpha.common.exchanges.binance.worker import BinanceFutures, BinanceSpot
from tradealpha.common.exchanges.binance.ticker import BinanceFuturesTicker
from tradealpha.common.exchanges.bitmex.bitmex import BitmexWorker
from tradealpha.common.exchanges.bybit.bybit import BybitInverseWorker, BybitLinearWorker
from tradealpha.common.exchanges.bybit.ticker import BybitLinearTicker, BybitInverseTicker
from tradealpha.common.exchanges.ftx.http import FtxWorker
from tradealpha.common.exchanges.ftx.ticker import FtxTicker
from tradealpha.common.exchanges.kucoin.kucoin import KuCoinFuturesWorker
from tradealpha.common.exchanges.okx.okx import OkxWorker

EXCHANGES = {
    worker.exchange: worker
    for worker in [
        BinanceFutures,
        BinanceSpot,
        BitmexWorker,
        FtxWorker,
        KuCoinFuturesWorker,
        BybitLinearWorker,
        BybitInverseWorker,
        OkxWorker,
    ]
}

EXCHANGE_TICKERS = {
    'ftx': FtxTicker,
    'binance-futures': BinanceFuturesTicker,
    'bybit-linear': BybitLinearTicker,
    'bybit-inverse': BybitInverseTicker
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
