import pytest

from common.exchanges import SANDBOX_CLIENTS
from common.messenger import Category, TableNames
from common.test_utils.fixtures import Channel
from database.models.client import ClientCreate

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    'data',
    [
        ClientCreate(
            name="dummy",
            exchange="binance-futures",
            api_key="invalid-key",
            api_secret="invalid-secret",
            extra_kwargs={}
        )
    ],
)
async def test_invalid_client(create_client, data):
    with create_client(data) as resp:
        assert resp.status_code == 400


@pytest.mark.parametrize(
    'redis_messages',
    [[
        Channel(TableNames.CLIENT, Category.NEW)
    ]],
    indirect=True
)
@pytest.mark.parametrize(
    'register_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_valid_client(redis_messages, create_client, register_client):
    await redis_messages.wait(0.5)


@pytest.mark.parametrize(
    'register_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_overview(register_client, api_client):
    resp = api_client.get('/api/v1/client')
    assert resp.status_code == 200
