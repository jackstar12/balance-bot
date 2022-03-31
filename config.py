from Exchanges.binance.binance import BinanceFutures, BinanceSpot
from Exchanges.bitmex import BitmexClient
from Exchanges.bybit import BybitClient
from Exchanges.ftx.ftx import FtxClient
from Exchanges.kucoin import KuCoinClient
from Exchanges.okx.okx import OkxClient

PREFIX = "c "
DATA_PATH = "data/"
ARCHIVE_PATH = "archive/"
FETCHING_INTERVAL_HOURS = 1
REKT_THRESHOLD = 0.5
REGISTRATION_MINIMUM = 1
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

LOG_OUTPUT_DIR = "LOGS/"

