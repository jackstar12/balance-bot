import asyncio
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from tests.mock import event_mock
from tradealpha.common.dbmodels import Client, Execution
from tradealpha.common.dbasync import db_select_all, db_all
from tradealpha.common.dbmodels.trade import Trade
from tradealpha.common.messenger import TableNames, Category, EVENT
from tests.conftest import Channel, Messages
from tradealpha.common.exchanges import SANDBOX_CLIENTS

pytestmark = pytest.mark.anyio


async def test_event_messages(event_service, test_user, messenger, db):

    async with Messages.create(
        Channel(TableNames.EVENT, EVENT.REGISTRATION_START),
        Channel(TableNames.EVENT, EVENT.START),
        Channel(TableNames.EVENT, EVENT.REGISTRATION_END),
        Channel(TableNames.EVENT, EVENT.END),
        messenger=messenger
    ) as listener:
        event = event_mock().get(test_user)
        db.add(event)
        await db.commit()
        await listener.wait(10)
        pass
