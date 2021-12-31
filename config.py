PREFIX = "c "
DATA_PATH = "data/"
FETCHING_INTERVAL_HOURS = 1
INITIAL_BALANCE = {
    "date": "01/12/2021 00:00:00",
    "amount": 100,
    "currency": "$"
}
REKT_THRESHOLD = 2.5
REKT_MESSAGES = [
    "{name} hat sich mit der Leverage vergriffen :cry:",
    "{name} gone **REKT**!",
    "{name} hat den SL vergessen..."
]
# Channels where the Rekt Messages are sent
REKT_GUILDS = [
    {
        "guild_id": 916370614598651934,
        "guild_channel": 917146534372601886
    },
    {
        "guild_id": 443583326507499520,
        "guild_channel": 704403630375305317
    }
]
CURRENCY_PRECISION = {
    '$': 2,
    'BTC': 5,
    'XBT': 5
}
CURRENCY_ALIASES = {
    'BTC': 'XBT',
    'XBT': 'BTC'
}
LOG_OUTPUT_DIR = "LOGS/"
