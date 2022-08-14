import pytest
from fastapi.testclient import TestClient

from tradealpha.api.app import app
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture(scope='session')
def api_client() -> TestClient:
    with TestClient(app) as c:
        yield c


@pytest.fixture
async def api_register_login(api_client):
    api_client.post(
        "/api/v1/register",
        json={
            "email": "test@gmail.com",
            "password": "strongpassword123",
        }
    )

    resp = api_client.post(
        "/api/v1/login",
        json={
            "email": "test@gmail.com",
            "password": "strongpassword123"
        }
    )
    resp_json = resp.json()
    assert resp_json["id"], "Login failed"

    api_client.headers['x-csrftoken'] = api_client.cookies['csrftoken']

    yield api_client

    api_client.delete('/api/v1/delete')
