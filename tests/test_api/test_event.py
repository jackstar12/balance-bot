from datetime import datetime, timedelta
from typing import Type, TypeVar

import pytest
import pytz
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from requests import Response

from tests.mock import event_mock
from tradealpha.api.routers.event import EventUpdate
from tradealpha.api.utils.responses import ResponseModel
from tradealpha.common.exchanges import SANDBOX_CLIENTS
from tradealpha.common.models import BaseModel
from tradealpha.common.models.eventinfo import EventInfo, EventDetailed

T = TypeVar('T', bound=BaseModel)


def parse_response(resp: Response, model: Type[T]) -> tuple[Response, T]:
    result = resp.json().get('result')
    try:
        return resp, (model(**result) if result else None)
    except (ValidationError, TypeError):
        return resp, ResponseModel(**resp.json())


@pytest.fixture
def event(api_client_logged_in):
    now = datetime.now(pytz.utc)

    resp = api_client_logged_in.post('/api/v1/event', json=jsonable_encoder(
        event_mock(now)
    ))

    assert resp.ok
    resp, event = parse_response(resp, EventInfo)

    yield event

    resp = api_client_logged_in.delete(f'/api/v1/event/{event.id}')
    assert resp.ok


def test_create_event(event):
    pass


def test_modify_event(event, api_client_logged_in):
    def modify(updates: EventUpdate):
        return parse_response(
            api_client_logged_in.patch(f'/api/v1/event/{event.id}', json=jsonable_encoder(
                updates
            )),
            EventInfo
        )

    resp, modified_event = modify(EventUpdate(
        name='Mock New'
    ))
    assert modified_event.name == 'Mock New'

    now = datetime.now(pytz.utc)

    resp, modified_event = modify(EventUpdate.construct(
        name='Mock Old',
        start=now,
        end=now - timedelta(seconds=5)
    ))
    assert resp.status_code == 422


@pytest.mark.parametrize(
    'confirmed_clients',
    [[SANDBOX_CLIENTS[0], SANDBOX_CLIENTS[0]]],
    indirect=True
)
def test_register_event(event, api_client_logged_in, confirmed_clients):

    for client in confirmed_clients:
        url = f'/api/v1/event/{event.id}/registrations/{client.id}'
        resp = api_client_logged_in.post(url)
        assert resp.ok

    resp, result = parse_response(
        api_client_logged_in.get(f'/api/v1/event/{event.id}'),
        EventDetailed
    )

    assert len(result.leaderboard) == len(confirmed_clients)
    for score in result.leaderboard:
        assert score.current_rank.value == 1

    for client in confirmed_clients:
        url = f'/api/v1/event/{event.id}/registrations/{client.id}'
        resp = api_client_logged_in.delete(url)
        assert resp.ok


def test_get_single(event, api_client_logged_in):
    resp, result = parse_response(
        api_client_logged_in.get(f'/api/v1/event/{event.id}'),
        EventDetailed
    )
    assert resp.ok
    assert result.id == event.id


def test_get_all(event, api_client_logged_in):
    resp = api_client_logged_in.get('/api/v1/event/')

    assert resp.ok
    results = resp.json().get('result')
    assert len(results) == 1
    result = EventInfo(**results[0])
    assert result.id == event.id
