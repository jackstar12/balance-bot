from balancebot.common.enums import Priority
REKT_THRESHOLD = 1

PRIORITY_INTERVALS = {
    Priority.LOW: 60,
    Priority.MEDIUM: 30,
    Priority.HIGH: 15,
    Priority.FORCE: 1
}

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

LOG_OUTPUT_DIR = "C:/Users/jkran/PycharmProjects/BalanceBot/LOGS/"
DATA_PATH = "C:/Users/jkran/PycharmProjects/BalanceBot/data/"
