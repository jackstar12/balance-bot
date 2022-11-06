from functools import wraps
from operator import and_
from time import perf_counter
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import greenlet_spawn

from api.routers.template import query_templates
from api.dependencies import get_messenger, get_db
from api.users import CurrentUser, get_current_user, get_token_backend, get_auth_grant_dependency, OptionalUser, \
    DefaultGrant
from api.models.completejournal import (
    JournalCreate, JournalInfo, DetailedChapter, JournalUpdate,
    ChapterCreate, ChapterUpdate, JournalDetailedInfo
)
from api.utils.responses import BadRequest, OK, CustomJSONResponse
from database.dbasync import db_unique, db_all, db_select, db_select_all, wrap_greenlet
from database.dbmodels.authgrant import JournalGrant, AuthGrant, ChapterGrant, AssociationType
from database.dbmodels.editing.chapter import Chapter as DbChapter
from database.dbmodels.client import add_client_filters, Client
from database.dbmodels.editing.journal import Journal, JournalType
from database.dbmodels.user import User

router = APIRouter(
    tags=["journal"],
    dependencies=[Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    },
    prefix='/journal'
)


async def query_journal(journal_id: int, user_id: UUID, *eager, session: AsyncSession) -> Journal:
    journal = await db_unique(
        select(Journal).where(
            Journal.id == journal_id,
            Journal.user_id == user_id
        ),
        session=session,
        *eager
    )
    # 621d1bb5-5bfd-49ef-8a53-a28cd540552f
    # 0a4ba32b-89ff-47eb-9d5c-6ddef522e1c2
    if not journal:
        raise HTTPException(404, 'Journal not found')
    return journal


async def query_clients(client_ids: list[int] | set[int], user: User, db_session: AsyncSession):
    clients = await db_all(
        add_client_filters(
            select(Client).filter(
                Client.id.in_(client_ids)
            ),
            user.id
        ),
        session=db_session
    )
    if len(clients) != len(client_ids):
        raise HTTPException(status_code=404, detail='Invalid client IDs')
    return clients


@router.post('', response_model=JournalInfo)
async def create_journal(body: JournalCreate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    clients = await query_clients(body.client_ids, user, db)
    if len(clients) != len(body.client_ids):
        raise BadRequest(detail='Invalid client IDs')
    journal = Journal(
        title=body.title,
        chapter_interval=body.chapter_interval,
        user=user,
        clients=clients,
        type=body.type
    )
    db.add(journal)

    if body.type == JournalType.INTERVAL and body.auto_generate:
        await journal.init(db)

    await db.commit()
    return JournalInfo.from_orm(journal)


JournalTokenBackend = get_token_backend(JournalGrant)


@router.get(
    '',
    description="Query all the users journals",
    response_model=list[JournalInfo]
)
@wrap_greenlet
def get_journals(grant: AuthGrant = Depends(DefaultGrant)):
    return CustomJSONResponse(
        content=jsonable_encoder(
            [
                JournalInfo.from_orm(journal)
                for journal in grant.journals
            ]
        )
    )


UserDep = get_current_user(auth_backends=[JournalTokenBackend])


@router.get('/{journal_id}', response_model=JournalDetailedInfo)
async def get_journal(journal_id: int,
                      grant: AuthGrant = Depends(get_auth_grant_dependency(association_table=JournalGrant)),
                      db: AsyncSession = Depends(get_db)):

    journal = await query_journal(
        journal_id, grant.user_id,
        Journal.default_template,
        Journal.clients,
        session=db
    )

    stmt = select(
        DbChapter.id,
        DbChapter.parent_id,
        DbChapter.title,
        DbChapter.data['start_date'],
        DbChapter.data['end_date'],
    ).where(
        DbChapter.journal_id == journal_id
    )

    if not grant.is_root_for(AssociationType.CHAPTER):
        stmt = stmt.join(
            ChapterGrant, and_(
                ChapterGrant.grant_id == grant.id,
                ChapterGrant.chapter_id == DbChapter.id
            )
        )

    result = await db.execute(stmt)

    await journal.update(db)
    return OK(
        result=JournalDetailedInfo(
            **journal.__dict__,
            client_ids=journal.client_ids,
            chapters_info=result.all()
        ).dict(exclude_none=True),
    )


@router.patch('/{journal_id}', response_model=JournalDetailedInfo)
async def update_journal(journal_id: int,
                         body: JournalUpdate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(
        journal_id,
        user.id,
        Journal.clients,
        session=db
    )
    # Check explicitly for None because falsy values shouldn't be ignored
    if body.title is not None:
        journal.title = body.title
    if body.overview is not None:
        journal.overview = body.overview
    if body.client_ids is not None:
        if body.client_ids != set(journal.client_ids):
            clients = await query_clients(body.client_ids, user, db)
            journal.clients = clients
            await journal.update(db)

    if body.default_template_id:
        journal.default_template_id = body.default_template_id

    await db.commit()
    return JournalDetailedInfo.from_orm(journal)


@router.delete('/{journal_id}')
async def delete_journal(journal_id: int,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(journal_id, user.id, session=db)
    if journal:
        await db.delete(journal)
        await db.commit()
    return OK('Deleted')


@router.get('/{journal_id}/trades')
async def get_journal_trades(journal_id: int,
                             user: User = Depends(CurrentUser),
                             db: AsyncSession = Depends(get_db)):
    journal = await query_journal(journal_id, user.id, session=db)

    await db_all(
        select(DbChapter.doc['doc']['content']['id']).filter(
            DbChapter.doc['doc']['type'] == 'trade-mention',
            DbChapter.journal_id == journal.id
        )
    )
