from balancebot.common.exchanges.binance.worker import BinanceFutures, BinanceSpot
from balancebot.common.exchanges.binance.ticker import BinanceFuturesTicker
from balancebot.common.exchanges.bitmex.bitmex import BitmexWorker
from balancebot.common.exchanges.bybit.bybit import BybitInverseWorker, BybitLinearWorker
from balancebot.common.exchanges.bybit.ticker import BybitLinearTicker, BybitInverseTicker
from balancebot.common.exchanges.ftx.http import FtxWorker
from balancebot.common.exchanges.ftx.ticker import FtxTicker
from balancebot.common.exchanges.kucoin.kucoin import KuCoinFuturesWorker
from balancebot.common.exchanges.okx.okx import OkxWorker

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
