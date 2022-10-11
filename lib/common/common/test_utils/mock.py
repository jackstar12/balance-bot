from datetime import datetime, timedelta

from core.utils import utc_now
from database.models.document import DocumentModel
from database.models.eventinfo import EventCreate


def event_mock(now: datetime = None):
    now = now or utc_now()
    return EventCreate(
        name='Mock',
        description=DocumentModel(type='doc'),
        registration_start=now + timedelta(seconds=2),
        start=now + timedelta(seconds=4),
        registration_end=now + timedelta(seconds=6),
        end=now + timedelta(seconds=8),
        public=True,
        location={'platform': 'web', 'data': {}},
        max_registrations=100,
    )
