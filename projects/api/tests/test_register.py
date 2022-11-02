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
    'confirmed_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_valid_client(confirmed_client):
    pass


@pytest.mark.parametrize(
    'confirmed_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_overview(confirmed_client, api_client):
    resp = api_client.get(f'/api/v1/client/{confirmed_client.id}')
    assert resp.status_code == 200
