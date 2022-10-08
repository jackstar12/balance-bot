from datetime import datetime, timedelta
from typing import Type, TypeVar

import pytest
import pytz
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from requests import Response

from database.models.document import DocumentModel
from database.models.eventinfo import EventInfo, EventDetailed
from api.routers.event import EventCreate, EventUpdate
from api.utils.responses import ResponseModel
from common.exchanges import SANDBOX_CLIENTS
from database.models import BaseModel

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

    resp = api_client_logged_in.post('/api/v1/event/', json=jsonable_encoder(
        EventCreate(
            name='Mock',
            description=DocumentModel(type='doc'),
            start=now + timedelta(seconds=10),
            end=now + timedelta(seconds=20),
            registration_start=now + timedelta(seconds=5),
            registration_end=now + timedelta(seconds=15),
            public=True,
            location={'platform': 'web', 'data': {}},
            max_registrations=100
        )
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
    'confirm_clients',
    [[SANDBOX_CLIENTS[0], SANDBOX_CLIENTS[0]]],
    indirect=True
)
def test_register_event(event, api_client_logged_in, confirm_clients):

    for client in confirm_clients:
        url = f'/api/v1/event/{event.id}/registrations/{client.id}'
        resp = api_client_logged_in.post(url)
        assert resp.ok

    resp, result = parse_response(
        api_client_logged_in.get(f'/api/v1/event/{event.id}'),
        EventDetailed
    )

    assert len(result.leaderboard) == len(confirm_clients)
    for score in result.leaderboard:
        assert score.current_rank.value == 1

    for client in confirm_clients:
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
