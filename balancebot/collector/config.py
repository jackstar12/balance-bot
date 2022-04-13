from balancebot.common.exchanges.ftx.ticker import FtxTicker
from balancebot.common.exchanges.binance.ticker import BinanceFuturesTicker

EXCHANGE_TICKERS = {
    'ftx': FtxTicker,
    'binance-futures': BinanceFuturesTicker
}
