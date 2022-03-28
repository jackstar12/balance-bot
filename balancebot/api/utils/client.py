from datetime import datetime
from typing import Optional

import balancebot.utils as utils
from balancebot.api.dbmodels.client import Client, get_client_query
from balancebot.api.dbmodels.user import User


def ratio(a: float, b: float):
    return round(a / (a + b), ndigits=3) if a + b > 0 else 0.5


def create_cilent_data_serialized(client: Client, since_date: datetime, to_date: datetime, currency: str = None):
    s = client.serialize(full=True, data=False)

    history = []
    s['daily'] = utils.calc_daily(
        client=client,
        forEach=lambda balance: history.append(balance.serialize(full=True, data=True, currency=currency)),
        throw_exceptions=False,
        since=since_date,
        to=to_date
    )
    s['history'] = history

    winning_days, losing_days = 0, 0
    for day in s['daily']:
        if day[2] > 0:
            winning_days += 1
        elif day[2] < 0:
            losing_days += 1

    s['daily_win_ratio'] = ratio(winning_days, losing_days)
    s['winning_days'] = winning_days
    s['losing_days'] = losing_days

    trades = []
    winners, losers = 0, 0
    avg_win, avg_loss = 0.0, 0.0
    for trade in client.trades:
        if since_date <= trade.initial.time <= to_date:
            trade = trade.serialize(data=True)
            if trade['status'] == 'win':
                winners += 1
                avg_win += trade['realized_pnl']
            elif trade['status'] == 'loss':
                losers += 1
                avg_loss += trade['realized_pnl']
            trades.append(trade)

    s['trades'] = trades
    s['win_ratio'] = ratio(winners, losers)
    s['winners'] = winners
    s['losers'] = losers
    s['avg_win'] = avg_win / (winners or 1)
    s['avg_loss'] = avg_loss / (losers or 1)
    s['action'] = 'NEW'

    return s


def get_user_client(user: User, id: int = None):
    client: Optional[Client] = None
    if id:
        client = get_client_query(user, id).first()
    elif user.discorduser:
        client = user.discorduser.global_client
    elif len(user.clients) > 0:
        client = user.clients[0]
    return client
