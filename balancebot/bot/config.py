from balancebot.common.exchanges.binance.binance import BinanceFutures, BinanceSpot
from balancebot.common.exchanges.bitmex.bitmex import BitmexClient
from balancebot.common.exchanges.bybit.bybit import BybitClient
from balancebot.common.exchanges.ftx.http import FtxClient
from balancebot.common.exchanges.kucoin.kucoin import KuCoinClient
from balancebot.common.exchanges.okx.okx import OkxClient

PREFIX = "c "
DATA_PATH = "C:/Users/jkran/PycharmProjects/BalanceBot/data/"
ARCHIVE_PATH = "C:/Users/jkran/PycharmProjects/BalanceBot/archive/"
FETCHING_INTERVAL_HOURS = 1
REKT_THRESHOLD = 5000
REGISTRATION_MINIMUM = 50
REKT_MESSAGES = [
    "{name} hat sich mit der Leverage vergriffen :cry:",
    "{name} gone **REKT**!",
    "{name} hat den SL vergessen..."
]
# Channels where the Rekt Messages are sent
REKT_GUILDS = [
    # Bot-Test
    {
        "guild_id": 916370614598651934,
        "guild_channel": 917146534372601886
    },
    # Next Level
    {
        "guild_id": 443583326507499520,
        "guild_channel": 704403630375305317
    }
]
CURRENCY_PRECISION = {
    '$': 2,
    'USD': 2,
    '%': 2,
    'BTC': 6,
    'XBT': 6,
    'ETH': 4
}
CURRENCY_ALIASES = {
    'BTC': 'XBT',
    'XBT': 'BTC',
    'USD': '$'
}
EXCHANGES = {
    'binance-futures': BinanceFutures,
    'binance-spot': BinanceSpot,
    'bitmex': BitmexClient,
    'ftx': FtxClient,
    'kucoin': KuCoinClient,
    'bybit': BybitClient,
    'okx': OkxClient
}
LOG_OUTPUT_DIR = "C:/Users/jkran/PycharmProjects/BalanceBot/LOGS/"

