import pytest

from fastapi.testclient import TestClient

from tradealpha.api.models.client import RegisterBody
from tradealpha.api.app import app
from tradealpha.common.dbmodels.client import Client


@pytest.fixture(scope="package")
def api_client():
    return TestClient(app)


@pytest.fixture
def api_register_login(api_client):

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
    assert resp.json()["id"], "Login failed"

    api_client.headers['x-csrftoken'] = api_client.cookies['csrftoken']

    yield api_client

    #api_client.post("/api/v1/unregister")



@pytest.fixture
def register_dummy_client(request, api_register_login):
    resp = api_register_login.post("/api/v1/client",
                    json={
                        **request.param.dict()
                    })
    pass



@pytest.mark.parametrize(
    'register_dummy_client',
    [RegisterBody(
        name="dummy",
        exchange="binance-futures",
        api_key="invalid-key",
        api_secret="invalid-secret",
        extra={}
    )],
    indirect=True
)
def test_info(api_client, register_dummy_client):
    assert 1
