import pytest


def test_register(api_client):
    api_client.post(

    )


def test_info(api_client, api_register_login):
    resp = api_client.get(
        "/api/v1/info"
    )

    assert resp