from functools import wraps
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import greenlet_spawn

from api.routers.journal import query_journal
from api.routers.template import query_templates
from api.dependencies import get_messenger, get_db
from api.users import CurrentUser, get_current_user, get_token_backend, get_auth_grant_dependency, OptionalUser
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
from database.models import InputID

router = APIRouter(
    tags=["chapter"],
    prefix='/chapter'
)


async def query_chapter(chapter_id: int,
                        user_id: UUID,
                        *eager,
                        session: AsyncSession,
                        **filters):
    chapter = await db_unique(
        select(DbChapter).filter(
            DbChapter.id == chapter_id,
            Journal.user_id == user_id
        ).filter_by(
            **filters
        ).join(
            DbChapter.journal
        ),
        session=session,
        *eager
    )
    if not chapter:
        raise HTTPException(404, 'Chapter not found')
    return chapter


@router.get('/{chapter_id}', response_model=DetailedChapter)
async def get_chapter(chapter_id: InputID,
                      grant: AuthGrant = Depends(get_auth_grant_dependency(ChapterGrant)),
                      db: AsyncSession = Depends(get_db)):
    chapter = await query_chapter(
        chapter_id,
        grant.user_id,
        grant.is_root_for(AssociationType.CHAPTER) and DbChapter.grants,
        # DbChapter.trades,
        session=db
    )

    return OK(result=DetailedChapter.from_orm(chapter).dict(exclude_none=True))


@router.get('/{chapter_id}/data', response_model=DetailedChapter)
async def get_chapter_data(chapter_id: InputID,
                           grant: AuthGrant = Depends(get_auth_grant_dependency(ChapterGrant)),
                           db: AsyncSession = Depends(get_db)):
    chapter = await query_chapter(
        chapter_id,
        grant.user_id,
        # DbChapter.trades,
        DbChapter.balances,
        session=db,
    )

    childs = await DbChapter.all_childs(chapter.id, db)

    data = [

    ]

    return DetailedChapter.from_orm(chapter)


@router.patch('/{chapter_id}')
async def update_chapter(chapter_id: InputID,
                         body: ChapterUpdate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    chapter = await query_chapter(
        chapter_id,
        user.id,
        session=db
    )
    if body.doc is not None:
        chapter.doc = body.doc
    if body.data:
        chapter.data = body.data
    await db.commit()
    return OK('OK')


@router.post('', response_model=DetailedChapter)
async def create_chapter(body: ChapterCreate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(body.journal_id, user.id, Journal.clients, session=db)

    template = None
    if body.template_id:
        template = await query_templates([body.template_id],
                                         user_id=user.id,
                                         session=db)

    new_chapter = journal.create_chapter(body.parent_id, template)

    db.add(new_chapter)
    await db.commit()
    return DetailedChapter.from_orm(new_chapter)


@router.delete('/{chapter_id}')
async def delete_chapter(chapter_id: InputID,
                         user: User = Depends(CurrentUser),
                         db=Depends(get_db)):
    chapter = await query_chapter(
        chapter_id,
        user.id,
        session=db
    )
    await db.delete(chapter)
    await db.commit()
    return OK('OK')
