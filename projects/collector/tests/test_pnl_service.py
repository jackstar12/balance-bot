import asyncio
import itertools
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from database.dbmodels import Client, Execution
from database.dbasync import db_select_all, db_all
from database.dbmodels.trade import Trade
from common.messenger import TableNames, Category
from common.test_utils.fixtures import Channel, Messages
from common.exchanges import SANDBOX_CLIENTS

pytestmark = pytest.mark.anyio


@pytest.fixture(scope='session')
def time():
    return datetime.now()


symbol = 'BTCUSDT'
size = Decimal('0.01')


@pytest.mark.parametrize(
    'db_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_realtime(pnl_service, time, db_client, db, ccxt_client, messenger, redis):
    db_client: Client

    prev_balance = await db_client.get_latest_balance(redis, db=db)

    async with Messages.create(
            Channel(TableNames.TRADE, Category.NEW),
            messenger=messenger
    ) as listener:
        ccxt_client.create_market_buy_order(symbol, float(size))

        await listener.wait(5)

    await asyncio.sleep(2.5)

    first_balance = await db_client.get_latest_balance(redis, db=db)

    assert prev_balance.realized != first_balance.realized

    async with Messages.create(
            Channel(TableNames.BALANCE, Category.LIVE),
            Channel(TableNames.TRADE, Category.UPDATE),
            messenger=messenger
    ) as listener:
        ccxt_client.create_market_sell_order(symbol, float(size / 2))
        await listener.wait(15)

    second_balance = await db_client.get_latest_balance(redis, db=db)
    assert first_balance.realized != second_balance.realized

    async with Messages.create(
            Channel(TableNames.TRADE, Category.FINISHED),
            messenger=messenger
    ) as listener:
        ccxt_client.create_market_sell_order(symbol, float(size / 2))
        await listener.wait(5)

    trades = await db_select_all(
        Trade,
        eager=[Trade.max_pnl, Trade.min_pnl],
        client_id=db_client.id
    )

    assert len(trades) == 1
    assert trades[0].qty == size
    assert trades[0].max_pnl.total != trades[0].min_pnl.total


@pytest.mark.parametrize(
    'db_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_imports(pnl_service, time, db_client):
    trades = await db_select_all(
        Trade,
        eager=[Trade.executions, Trade.max_pnl, Trade.min_pnl],
        client_id=db_client.id
    )
    execs = list(
        itertools.chain.from_iterable(trade.executions for trade in trades)
    )

    assert len(execs) >= 3
    assert sum(e.qty for e in execs) == 2 * size
    assert sum(e.effective_qty for e in execs).is_zero()

    assert len(trades) == 1
    trade = trades[0]
    assert trade.open_qty.is_zero()
    assert trade.qty == size
    assert trade.max_pnl.total != trades[0].min_pnl.total
