import asyncio

import pytest

from fastapi.testclient import TestClient

from api.app import app

test_client = TestClient(app)
pytestmark = pytest.mark.anyio


async def test_dies():
    await asyncio.sleep(0.1)
    assert 1


async def test_info(api_client_logged_in):
    resp = api_client_logged_in.get("/api/v1/info")
    assert resp.ok
