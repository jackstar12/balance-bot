from datetime import datetime
from typing import Optional

import pytz
import sqlalchemy.exc
from fastapi import APIRouter, Depends
from pydantic import validator
from sqlalchemy import select, or_, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_messenger, get_db
from api.users import CurrentUser, get_current_user
from api.utils.responses import BadRequest, OK, InternalError, ResponseModel, NotFound
from database import utils as dbutils
from database.dbasync import db_first, redis, db_unique
from database.dbmodels import Client
from database.dbmodels.event import Event as EventDB, EventState
from database.dbmodels.score import EventEntry as EventEntryDB
from database.dbmodels.user import User
from database.utils import add_client_filters
from database.models import BaseModel
from database.models.document import DocumentModel
from database.models.eventinfo import EventInfo, EventDetailed, EventCreate, EventEntry, Leaderboard

router = APIRouter(
    tags=["event"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    },
    prefix='/event'
)


def add_event_filters(stmt,
                      user: User,
                      owner=False):
    if owner:
        return stmt.filter(
            EventDB.owner_id == user.id
        )
    else:
        # stmt = stmt\
        #    .join(EventScoreDB
        #    , EventScoreDB
        #    .event_id == event_id)\
        #    .join(EventScoreDB
        #    .client)\
        #    .filter(
        #    or_(
        #        Client.user_id == user.id,
        #        EventDB.public,
        #        EventDB.owner_id == user.id
        #    )
        # )
        return stmt.filter(
            or_(
                EventDB.public,
                EventDB.owner_id == user.id
            )
        )


def query_event(event_id: int,
                user: User,
                *eager,
                owner=False,
                db: AsyncSession):
    stmt = add_event_filters(
        select(EventDB).filter(
            EventDB.id == event_id
        ),
        user=user,
        owner=owner,
    )

    return db_first(stmt, *eager, EventDB.clients, session=db)


def create_event_dep(*eager, owner=False):
    async def dependency(event_id: int,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)) -> EventDB:
        return await query_event(event_id, user, *eager, owner=owner, db=db)

    return dependency


default_event = create_event_dep()


@router.post('', response_model=ResponseModel[EventInfo])
async def create_event(body: EventCreate,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    event = EventDB(
        **body.__dict__,
        owner=user,
        # actions=[
        #     Action(**action.dict()) for action in body.actions
        # ] if body.actions else None
    )

    try:
        event.validate()
        await event.validate_location(redis)
    except ValueError as e:
        return BadRequest(str(e))

    active_event = await dbutils.get_event(location=body.location,
                                           throw_exceptions=False,
                                           db=db)

    if active_event:
        if body.start < active_event.end:
            return BadRequest(f"Event can't start while other event ({active_event.name}) is still active")
        if body.registration_start < active_event.registration_end:
            return BadRequest(
                f"Event registration can't start while other event ({active_event.name}) is still open for registration")

    active_registration = await dbutils.get_event(location=body.location, state=EventState.REGISTRATION,
                                                  throw_exceptions=False,
                                                  db=db)

    if active_registration:
        if body.registration_start < active_registration.registration_end:
            return BadRequest(
                f"Event registration can't start while other event ({active_registration.name}) is open for registration")

    db.add(event)
    await db.commit()

    return OK(
        result=EventInfo.from_orm(event)
    )


EventUserDep = get_current_user(
    (User.events, EventDB.actions)
)


@router.get('', response_model=ResponseModel[list[EventInfo]])
async def get_events(user: User = Depends(EventUserDep)):
    return OK(
        result=[
            EventInfo.from_orm(event) for event in user.events
        ]
    )


@router.get('/{event_id}', response_model=ResponseModel[EventDetailed])
async def get_event(event_id: int,
                    user: User = Depends(CurrentUser),
                    db: AsyncSession = Depends(get_db)):
    event = await query_event(event_id,
                              user,
                              db=db, owner=False)

    if event:
        return OK(
            result=EventDetailed.from_orm(event)
        )
    else:
        return BadRequest('Invalid event id')


@router.get('/{event_id}/leaderboard', response_model=ResponseModel[Leaderboard])
async def get_event(event_id: int,
                    user: User = Depends(CurrentUser),
                    db: AsyncSession = Depends(get_db)):
    event = await query_event(event_id,
                              user,
                              (EventDB.entries, [
                                  EventEntryDB.client,
                                  EventEntryDB.init_balance
                              ]),
                              db=db, owner=False)

    leaderboard = await event.get_leaderboard()

    if event:
        return OK(
            result=leaderboard
        )
    else:
        return BadRequest('Invalid event id')


@router.get('/{event_id}/registrations/{client_id}', response_model=ResponseModel[EventEntry])
async def get_event_registration(event_id: int,
                                 client_id: int,
                                 user: User = Depends(CurrentUser),
                                 db: AsyncSession = Depends(get_db)):
    score = await db_unique(
        add_event_filters(
            select(EventEntryDB
                   ).filter_by(
                client_id=client_id, event_id=event_id
            ), user=user, owner=False
        ),
        (EventEntryDB.client, Client.history),
        session=db
    )

    if score:
        return OK(result=EventEntry.from_orm(score))
    else:
        return BadRequest('Invalid event or client id. You might miss authorization')


class EventUpdate(BaseModel):
    name: Optional[str]
    description: Optional[DocumentModel]
    start: Optional[datetime]
    end: Optional[datetime]
    registration_start: Optional[datetime]
    registration_end: Optional[datetime]
    public: Optional[bool]
    max_registrations: Optional[int]

    @validator("start", "registration_start", "end", "registration_end")
    def cant_update_past(cls, v):
        now = datetime.now(pytz.utc)
        if v and v < now:
            raise ValueError(f'Can not udpate date from the past')
        return v


owner_event = create_event_dep(EventDB.clients, owner=True)


@router.patch('/{event_id}', response_model=ResponseModel[EventInfo])
async def update_event(body: EventUpdate,
                       event: EventDB = Depends(owner_event),
                       db: AsyncSession = Depends(get_db)):
    # dark magic
    for key, value in body.dict(exclude_none=True).items():
        setattr(event, key, value)

    try:
        event.validate()
    except ValueError as e:
        await db.rollback()
        return BadRequest(str(e))

    await db.commit()

    return OK('Event Updated', result=EventInfo.from_orm(event))


# Actions have to be loaded and deleted in-app because of dynamic functionality of actions
delete_dep = create_event_dep(EventDB.actions)


@router.delete('/{event_id}')
async def delete_event(event: EventDB = Depends(delete_dep),
                       db: AsyncSession = Depends(get_db)):
    if event:
        await db.delete(event)
        await db.commit()
        return OK('Deleted')
    else:
        return BadRequest('You can not delete this event')


@router.post('/{event_id}/registrations/{client_id}')
async def register_event(client_id: int,
                         event: EventDB = Depends(default_event),
                         db: AsyncSession = Depends(get_db),
                         user: User = Depends(CurrentUser)):
    client_id = await db_first(
        add_client_filters(
            select(Client.id), user=user, client_ids=[client_id]
        ),
        session=db
    )
    if client_id:
        try:
            result = await db.execute(
                insert(EventEntryDB).values(
                    event_id=event.id, client_id=client_id
                )
            )
        except sqlalchemy.exc.IntegrityError:
            return BadRequest('Already signed up')
        # db.add(
        #     EventScoreDB
        #     ()
        # )
        await db.commit()
        if result.rowcount == 1:
            return OK('Signed Up')
        else:
            return InternalError('Sign up failed')
    else:
        return BadRequest('Invalid client ID')


@router.delete('/{event_id}/registrations/{client_id}')
async def unregister_event(client_id: int,
                           event: EventDB = Depends(default_event),
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(CurrentUser)):
    client_id = await db_first(
        add_client_filters(
            select(Client.id), user=user, client_ids=[client_id]
        ),
        session=db
    )
    if client_id:
        result = await db.execute(
            delete(EventEntryDB
                   ).filter_by(
                event_id=event.id, client_id=client_id
            )
        )
        # db.add(
        #     EventScoreDB
        #     ()
        # )
        await db.commit()
        if result.rowcount == 1:
            return OK('Unregistered form the Event')
        else:
            return NotFound('Invalid event id')
    else:
        return NotFound('Invalid client id')
