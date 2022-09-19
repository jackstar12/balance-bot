import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from tradealpha.common.models.client import ClientCreate
from tradealpha.api.models.client import ClientInfo
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
def api_client_logged_in(api_client):
    api_client.post(
        "/api/v1/register",
        json={
            "email": "test@gmail.com",
            "password": "strongpassword123",
        }
    )

    resp = api_client.post(
        "/api/v1/login",
        data={
            "username": "test@gmail.com",
            "password": "strongpassword123"
        }
    )
    assert resp.ok, "Login failed"

    # api_client.headers['x-csrftoken'] = api_client.cookies['csrftoken']

    yield api_client

    resp = api_client.delete('/api/v1/delete')
    assert resp.ok


@pytest.fixture  #
def create_client(api_client_logged_in):

    def _register(data: ClientCreate):
        return api_client_logged_in.post("/api/v1/client",
                                         json=jsonable_encoder(data))

    return _register


@pytest.fixture
def confirm_clients(api_client, create_client, request):
    results = []

    for data in request.param:
        resp = create_client(data)
        assert resp.status_code == 200

        resp = api_client.post('/api/v1/client/confirm', json={**resp.json()})
        assert resp.status_code == 200

        results.append(ClientInfo(**resp.json()))

    yield results

    for result in results:
        resp = api_client.delete(f'/api/v1/client/{result.id}')
        assert resp.status_code == 200


@pytest.fixture
def confirm_client(api_client, confirm_clients):

    def _confirm(data: ClientCreate):
        with confirm_clients(data) as clients:
            return clients[0]

    return _confirm


@pytest.fixture
def register_client(request, confirm_client):
    with confirm_client(request.param) as client:
        yield client
