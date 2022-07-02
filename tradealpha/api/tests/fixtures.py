import pytest
from fastapi.testclient import TestClient

from tradealpha.api.app import app
from tradealpha.common.dbmodels.client import Client


@pytest.fixture(scope="package")
def api_client():
    return TestClient(app)


@pytest.fixture()
def api_register_login(api_client):

    api_client.post(
        "/api/v1/register",
        data={
            "email": "test@gmail.com",
            "password": "strongpassword123",
        }
    )

    api_client.post(
        "/api/v1/login",
        data={
            "email": "test@gmail.com",
            "password": "strongpassword123"
        }
    )

    yield api_client

    api_client.post("/api/v1/unregister")


@pytest.fixture()
def register_dummy_client(exchange, api_key, api_secret, kwargs, api_client):
    api_client.post("/api/v1/client",
                    data={
                        "name": "dummy",
                        "exchange": exchange,
                        "api_key": api_key,
                        "api_secret": api_secret,
                        **kwargs
                    })



