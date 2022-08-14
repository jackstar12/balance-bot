import pytest

from tradealpha.common import utils
from tradealpha.common.exchanges import SANDBOX_CLIENTS
from tradealpha.common.messenger import Category, NameSpace
from tests.conftest import Channel
from tradealpha.api.models.client import ClientCreate, ClientInfo

pytestmark = pytest.mark.anyio


@pytest.fixture
async def register_client(request, api_register_login):
    yield api_register_login.post("/api/v1/client",
                                  json={
                                      **request.param.dict()
                                  })


@pytest.fixture
async def confirm_client(api_client, register_client):
    assert register_client.status_code == 200

    resp = api_client.post('/api/v1/client/confirm', json=register_client.json())
    assert resp.status_code == 200

    client_info = ClientInfo(**resp.json())

    yield client_info

    resp = api_client.delete(f'/api/v1/client/{client_info.id}')
    assert resp.status_code == 200


@pytest.mark.parametrize(
    'register_client',
    [
        ClientCreate(
            name="dummy",
            exchange="binance-futures",
            api_key="invalid-key",
            api_secret="invalid-secret",
            extra_kwargs={}
        )
    ],
    indirect=True
)
async def test_invalid_client(register_client):
    assert register_client.status_code == 400


@pytest.mark.parametrize(
    'redis_messages',
    [[
        Channel(utils.join_args(NameSpace.CLIENT, Category.NEW), pattern=True)
    ]],
    indirect=True
)
@pytest.mark.parametrize(
    'register_client',
    SANDBOX_CLIENTS,
    indirect=True
)
async def test_valid_client(redis_messages, confirm_client, register_client):
    await redis_messages.wait(0.5)
