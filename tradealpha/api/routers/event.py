from datetime import datetime
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.models.event import Event
from common import dbutils
from common.dbasync import db_select
from tradealpha.api.dependencies import CurrentUser, get_messenger, get_db
from tradealpha.api.utils.responses import BadRequest
from tradealpha.common import utils
from tradealpha.common.models import BaseModel
from tradealpha.common.dbmodels.event import Event as EventDB

router = APIRouter(
    tags=["client"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    }
)


class EventCreate(BaseModel):
    name: str
    description: str
    start: datetime
    end: datetime
    registration_start: datetime
    registration_end: datetime
    location: dict


@router.post('/')
async def register_event(body: EventCreate,
                         db: AsyncSession = Depends(get_db)):
    if body.start >= body.end:
        return BadRequest("Start time can't be after end time.")
    if body.registration_start >= body.registration_end:
        return BadRequest("Registration start can't be after registration end")
    if body.registration_end < body.start:
        return BadRequest("Registration end should be after or at event start")
    if body.registration_end > body.end:
        return BadRequest("Registration end can't be after event end.")
    if body.registration_start > body.start:
        return BadRequest("Registration start should be before event start.")

    active_event = await dbutils.get_event(location=body.location, throw_exceptions=False)

    if active_event:
        if body.start < active_event.end:
            return BadRequest(f"Event can't start while other event ({active_event.name}) is still active")
        if body.registration_start < active_event.registration_end:
            return BadRequest(
                f"Event registration can't start while other event ({active_event.name}) is still open for registration")

    active_registration = await dbutils.get_event(location=body.location, state='registration',
                                                  throw_exceptions=False)

    if active_registration:
        if body.registration_start < active_registration.registration_end:
            return BadRequest(
                f"Event registration can't start while other event ({active_registration.name}) is open for registration")

    event = EventDB(
        name=body.name,
        description=body.description,
        start=body.start,
        end=body.end,
        registration_start=body.registration_start,
        registration_end=body.registration_end,
        location=body.location
    )
    db.add(event)
    await db.commit()

    return Event.from_orm(event)


@router.get('/{event_id}')
async def get_event(event_id: int,
                    db: AsyncSession = Depends(get_db)):
    event = await db_select(EventDB, )