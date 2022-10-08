from datetime import datetime
from typing import Optional

import pytz
from fastapi import APIRouter, Depends
from pydantic import validator
from sqlalchemy import select, or_, insert, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import object_session

from api.dependencies import get_messenger, get_db
from api.users import CurrentUser, get_current_user
from database.models.eventinfo import EventInfo, EventDetailed, EventCreate, EventScore
from api.utils.responses import BadRequest, OK, InternalError, ResponseModel, NotFound
from database import utils as dbutils
from database.dbasync import db_first, db_del_filter, redis, db_unique
from database.dbmodels import Client
from database.dbmodels.event import Event as EventDB, EventState
from database.dbmodels.score import EventScore as EventScoreDB

from database.models.document import DocumentModel
from database.dbmodels.user import User
from database.utils import add_client_filters
from common.messenger import Messenger, TableNames, Category
from database.models import BaseModel

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
        owner=owner
    )

    return db_first(stmt, *eager, session=db)


async def event_dep(event_id: int,
                    user: User = Depends(CurrentUser),
                    db: AsyncSession = Depends(get_db)) -> EventDB:
    return await query_event(event_id, user, db=db)


async def owner_event_dep(event_id: int,
                          user: User = Depends(CurrentUser),
                          db: AsyncSession = Depends(get_db)) -> EventDB:
    return await query_event(event_id, user, owner=True, db=db)


@router.post('/', response_model=ResponseModel[EventInfo])
async def create_event(body: EventCreate,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    event = EventDB(**body.__dict__, owner=user)

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
    User.events
)


@router.get('/', response_model=ResponseModel[list[EventInfo]])
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

    await EventDB.save_leaderboard(event_id, db)
    await db.commit()

    event = await query_event(event_id,
                              user,
                              EventDB.registrations,
                              (EventDB.leaderboard, [
                                  EventScoreDB.current_rank,
                                  EventScoreDB.client
                              ]),
                              db=db, owner=False)

    if event:
        return OK(
            result=EventDetailed.from_orm(event)
        )
    else:
        return BadRequest('Invalid event id')


@router.get('/{event_id}/registrations/{client_id}', response_model=ResponseModel[EventScore])
async def get_event_registration(event_id: int,
                                 client_id: int,
                                 user: User = Depends(CurrentUser),
                                 db: AsyncSession = Depends(get_db)):

    score = await db_unique(
        add_event_filters(
            select(EventScoreDB
                   ).filter_by(
                client_id=client_id, event_id=event_id
            ), user=user, owner=False
        ),
        (EventScoreDB.client, Client.history),
        session=db
    )

    if score:
        return OK(result=EventScore.from_orm(score))
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


@router.patch('/{event_id}', response_model=ResponseModel[EventInfo])
async def update_event(body: EventUpdate,
                       event: EventDB = Depends(owner_event_dep),
                       db: AsyncSession = Depends(get_db),
                       messenger: Messenger = Depends(get_messenger)):
    assert db.sync_session == object_session(event)
    now = datetime.now(pytz.utc)

    # dark magic
    for key, value in body.dict(exclude_none=True).items():
        setattr(event, key, value)

    try:
        event.validate()
    except ValueError as e:
        await db.rollback()
        return BadRequest(str(e))

    await db.commit()

    messenger.pub_channel(TableNames.EVENT, Category.UPDATE,
                          {'id': event.id}, event.id)

    return OK('Event Updated', result=EventInfo.from_orm(event))


@router.delete('/{event_id}')
async def delete_event(event_id: int,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db),
                       messenger: Messenger = Depends(get_messenger)):
    result = await db_del_filter(
        EventDB,
        session=db,
        id=event_id, owner_id=user.id
    )
    if result.rowcount == 1:
        await db.commit()
        messenger.pub_channel(TableNames.EVENT,
                              Category.DELETE,
                              {'id': event_id})
        return OK('Deleted')
    else:
        return BadRequest('You can not delete this event')


@router.post('/{event_id}/registrations/{client_id}')
async def register_event(client_id: int,
                         event: EventDB = Depends(event_dep),
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
            insert(EventScoreDB
                   ).values(
                event_id=event.id, client_id=client_id
            )
        )
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
                           event: EventDB = Depends(event_dep),
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
            delete(EventScoreDB
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
