from datetime import datetime
from operator import and_
from typing import Optional
from uuid import UUID

import pytz
import sqlalchemy.exc
from fastapi import APIRouter, Depends
from fastapi.params import Path, Query
from pydantic import validator
from sqlalchemy import select, or_, insert, delete, asc
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from api.users import CurrentUser, get_current_user, get_auth_grant_dependency, DefaultGrant
from api.utils.responses import BadRequest, OK, InternalError, ResponseModel, NotFound
from database import utils as dbutils
from database.dbasync import db_first, redis, db_unique, wrap_greenlet, db_all
from database.dbmodels import Client
from database.dbmodels.authgrant import AuthGrant, EventGrant
from database.dbmodels.event import Event as EventDB, EventState, EventEntry
from database.dbmodels.evententry import EventEntry as EventEntryDB, EventScore as EventScoreDB
from database.dbmodels.user import User
from database.dbmodels.client import add_client_filters
from database.models import BaseModel, InputID, OutputID, OrmBaseModel
from database.models.document import DocumentModel
from database.models.eventinfo import EventInfo, EventDetailed, EventCreate, Leaderboard, Summary, \
    EventEntry, EventEntryDetailed, EventScore
from core.utils import groupby

router = APIRouter(
    tags=["event"],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    },
    prefix='/event'
)


def event_dep(*eager, root_only=False):
    async def dependency(event_id: InputID,
                         grant: AuthGrant = Depends(
                             get_auth_grant_dependency(EventGrant, root_only=root_only)
                         ),
                         db: AsyncSession = Depends(get_db)) -> EventDB:
        stmt = select(EventDB).filter(
            EventDB.id == event_id,
            EventDB.owner_id == grant.user_id
        )

        event = await db_first(stmt, *eager, EventDB.clients, session=db)

        if not event:
            raise BadRequest('Invalid event id')
        return event

    return dependency


default_event = event_dep()


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
        raise BadRequest(str(e))

    active_event = await dbutils.get_event(location=body.location,
                                           throw_exceptions=False,
                                           db=db)

    if active_event:
        if body.start < active_event.end:
            raise BadRequest(f"Event can't start while other event ({active_event.name}) is still active")
        if body.registration_start < active_event.registration_end:
            raise BadRequest(
                f"Event registration can't start while other event ({active_event.name}) is still open for registration")

    active_registration = await dbutils.get_event(location=body.location, state=EventState.REGISTRATION,
                                                  throw_exceptions=False,
                                                  db=db)

    if active_registration:
        if body.registration_start < active_registration.registration_end:
            raise BadRequest(
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
@wrap_greenlet
def get_events(grant: AuthGrant = Depends(DefaultGrant)):
    return OK(
        result=[EventInfo.from_orm(event) for event in grant.events]
    )


@router.get('/{event_id}', response_model=ResponseModel[EventDetailed])
async def get_event(event: EventDB = Depends(event_dep(EventDB.owner,
                                                       (EventDB.entries, [
                                                           EventEntryDB.client,
                                                           EventEntryDB.user,
                                                           EventEntryDB.init_balance
                                                       ])))):
    return OK(
        result=EventDetailed.from_orm(event)
    )


SummaryEvent = event_dep(
    (EventDB.entries,
     [
         EventEntryDB.client,
         EventEntryDB.init_balance
     ])
)


@router.get('/{event_id}/leaderboard', response_model=ResponseModel[Leaderboard])
async def get_event(db: AsyncSession = Depends(get_db),
                    date: datetime = None,
                    event: EventDB = Depends(SummaryEvent)):
    leaderboard = await event.get_leaderboard(date)
    await db.commit()

    return OK(result=leaderboard)


EventAuth = get_auth_grant_dependency(EventGrant)


@router.get('/{event_id}/summary', response_model=ResponseModel[Summary])
async def get_summary(event: EventDB = Depends(SummaryEvent),
                      date: datetime = None):
    summary = await event.get_summary(date)
    return OK(result=summary)


class EntryHistoryResponse(OrmBaseModel):
    by_entry: dict[OutputID, list[EventScore]]


@router.get('/{event_id}/registrations/history',
            response_model=ResponseModel[EntryHistoryResponse],
            dependencies=[Depends(EventAuth)])
async def get_event_entry_history(event_id: InputID,
                                  entry_ids: list[InputID] = Query(alias='entry_id'),
                                  db: AsyncSession = Depends(get_db)):
    scores = await db_all(
        select(EventScoreDB).where(
            EventScoreDB.entry_id.in_(entry_ids),
            EventEntryDB.event_id == event_id
        ).join(
            EventScoreDB.entry
        ).order_by(
            asc(EventScoreDB.time)
        ),
        session=db
    )

    grouped = groupby(scores or [], 'entry_id')

    return OK(result=EntryHistoryResponse(by_entry=grouped))


@router.get('/{event_id}/registrations/{entry_id}',
            response_model=ResponseModel[EventEntryDetailed],
            dependencies=[Depends(EventAuth)])
async def get_event_entry(event_id: int,
                          entry_id: int,
                          db: AsyncSession = Depends(get_db)):
    score = await db_unique(
        select(EventEntryDB).filter_by(
            id=entry_id,
            event_id=event_id
        ),
        EventEntryDB.rank_history,
        session=db
    )

    if score:
        return OK(result=EventEntryDetailed.from_orm(score))
    else:
        raise BadRequest('Invalid event or entry id. You might miss authorization')



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


@router.patch('/{event_id}', response_model=ResponseModel[EventInfo])
async def update_event(body: EventUpdate,
                       event: EventDB = Depends(event_dep(EventDB.clients, root_only=True)),
                       db: AsyncSession = Depends(get_db)):
    # dark magic
    for key, value in body.dict(exclude_none=True).items():
        setattr(event, key, value)

    try:
        event.validate()
    except ValueError as e:
        await db.rollback()
        raise BadRequest(str(e))

    await db.commit()

    return OK('Event Updated', result=EventInfo.from_orm(event))


@router.delete('/{event_id}')
async def delete_event(event: EventDB = Depends(event_dep(EventDB.actions, root_only=True)),
                       db: AsyncSession = Depends(get_db)):
    if event:
        await db.delete(event)
        await db.commit()
        return OK('Deleted')
    else:
        raise BadRequest('You can not delete this event')


class EventJoinBody(BaseModel):
    client_id: InputID


@router.post('/{event_id}/registrations', response_model=EventJoinBody)
async def join_event(body: EventJoinBody,
                     event: EventDB = Depends(default_event),
                     db: AsyncSession = Depends(get_db),
                     grant: AuthGrant = Depends(EventAuth)):
    client_id = await db_first(
        add_client_filters(
            select(Client.id), user_id=grant.user_id, client_ids=[body.client_id]
        ),
        session=db
    )
    if client_id:
        try:
            result = await db.execute(
                insert(EventEntryDB).values(
                    event_id=event.id,
                    client_id=client_id,
                    user_id=grant.user_id
                )
            )
        except sqlalchemy.exc.IntegrityError:
            raise BadRequest('Already signed up')
        # db.add(
        #     EventScoreDB
        #     ()
        # )
        await db.commit()
        if result.rowcount == 1:
            return OK('Signed Up')
        else:
            raise InternalError('Sign up failed')
    else:
        raise BadRequest('Invalid client ID')


@router.delete('/{event_id}/registrations/{entry_id}')
async def unregister_event(event_id: int,
                           entry_id: int = None,
                           db: AsyncSession = Depends(get_db),
                           user: User = Depends(CurrentUser)):
    stmt = delete(EventEntryDB).filter_by(event_id=event_id, user_id=user.id)
    result = await db.execute(
        stmt.filter_by(id=entry_id) if entry_id else stmt
    )
    await db.commit()
    if result.rowcount == 1:
        return OK('Unregistered form the Event')
    else:
        raise NotFound('Invalid entry id')
