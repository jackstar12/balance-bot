import pytest
from fastapi.testclient import TestClient

from balancebot.api.app import app
from balancebot.common.dbmodels.client import Client


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
def register_dummy_client(api_client):

    api_client.post("/api/v1/client",
                    data={

                    })

    return Client(

    )



