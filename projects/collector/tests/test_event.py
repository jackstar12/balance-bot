import pytest

from common.test_utils.fixtures import Channel, Messages
from common.messenger import TableNames, EVENT
from common.test_utils.mock import event_mock

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
