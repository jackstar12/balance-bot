from datetime import date
from decimal import Decimal
from typing import Optional, List, NamedTuple
from typing import Optional

from fastapi import APIRouter, Depends, Body, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from balancebot.api.dependencies import CurrentUser, get_messenger, CurrentUserDep, get_db
from balancebot.api.models.amount import FullBalance
from balancebot.api.models.completejournal import JournalCreate, JournalInfo, CompleteJournal, Chapter, JournalUpdate, \
    ChapterInfo, ChapterCreate, ChapterUpdate
from balancebot.common.dbmodels.chapter import Chapter as DbChapter
from balancebot.api.utils.client import get_user_client
from balancebot.api.utils.responses import BadRequest, OK, NotFound
from balancebot.common.database_async import async_session, db_unique, db_all
from balancebot.common.dbmodels.client import add_client_filters, Client
from balancebot.common.dbmodels.journal import Journal
from balancebot.common.dbmodels.user import User
from balancebot.common.models.gain import Gain

router = APIRouter(
    tags=["journal"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    },
    prefix='/journal'
)


async def query_chapter(journal_id: int,
                        user: User,
                        *eager,
                        session: AsyncSession,
                        **filters):
    chapter = await db_unique(
        select(DbChapter).filter(
            DbChapter.journal_id == journal_id,
            Journal.user_id == user.id
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


async def query_journal(journal_id: int, user: User, *eager, session: AsyncSession) -> Journal:
    journal = await db_unique(
        select(Journal).filter(
            Journal.id == journal_id,
            Journal.user_id == user.id
        ),
        session=session,
        *eager
    )
    if not journal:
        raise HTTPException(404, 'Journal not found')
    return journal


async def query_clients(client_ids: list[int] | set[int], user: User, db_session: AsyncSession):
    clients = await db_all(
        add_client_filters(
            select(Client).filter(
                Client.id.in_(client_ids)
            ),
            user
        ),
        session=db_session
    )
    if len(clients) != len(client_ids):
        raise HTTPException(status_code=404, detail='Invalid client IDs')
    return clients


@router.post('/')
async def create_journal(body: JournalCreate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    clients = await query_clients(body.clients, user, db)
    if len(clients) != len(body.clients):
        return BadRequest(detail='Invalid client IDs')
    journal = Journal(
        title=body.title,
        chapter_interval=body.chapter_interval,
        user=user,
        clients=clients
    )
    await journal.init(db)
    return JournalInfo.from_orm(journal)


@router.get('/')
async def get_journals(user: User = Depends(CurrentUserDep(User.journals))) -> List[JournalInfo]:
    return [
        JournalInfo.from_orm(journal)
        for journal in user.journals
    ]


@router.get('/{journal_id}')
async def get_journal(journal_id: int, user: User = Depends(CurrentUser)):
    journal = await query_journal(
        journal_id,
        user,
        session=async_session
    )

    return JournalInfo.from_orm(journal)


@router.patch('/{journal_id}')
async def update_journal(journal_id: int,
                         body: JournalUpdate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(
        journal_id,
        user,
        session=async_session
    )
    # Check explicitly for None because falsy values shouldn't be ignored
    if body.title is not None:
        journal.title = body.title
    if body.notes is not None:
        journal.notes = body.notes
    if body.clients is not None:
        if body.clients != set(journal.clients):
            clients = await query_clients(body.clients, user, db)
            journal.clients = clients

            await journal.re_init(db)

    return JournalInfo.from_orm(journal)


@router.delete('/{journal_id}')
async def delete_journal(journal_id: int, user: User = Depends(CurrentUser)):
    journal = await query_journal(journal_id, user, session=async_session)
    if journal:
        await async_session.delete(journal)
        await async_session.commit()
    return OK('Deleted')


@router.get('/{journal_id}/chapters')
async def get_chapters(journal_id: int, user: User = Depends(CurrentUser)):
    journal = await query_journal(
        journal_id, user,
        (Journal.chapters, DbChapter.balances),
        session=async_session
    )

    if not journal:
        return NotFound('Unknown journal id')

    return [
        ChapterInfo.from_orm(chapter)
        for chapter in journal.chapters
    ]


@router.get('/{journal_id}/chapters/{chapter_id}')
async def get_chapter(journal_id: int, chapter_id: int, user: User = Depends(CurrentUser)):
    chapter = await query_chapter(
        journal_id,
        user,
#        DbChapter.trades,
        DbChapter.balances,
        session=async_session,
        id=chapter_id
    )

    return Chapter.from_orm(chapter)


@router.patch('/{journal_id}/chapters/{chapter_id}')
async def update_chapter(journal_id: int,
                         chapter_id: int,
                         body: ChapterUpdate,
                         user: User = Depends(CurrentUser)):
    chapter = await query_chapter(
        journal_id,
        user,
        session=async_session,
        id=chapter_id
    )
    if body.notes is not None:
        chapter.notes = body.notes
    await async_session.commit()
    return OK('OK')


@router.post('/{journal_id}/chapters')
async def create_chapter(journal_id: int,
                         body: ChapterCreate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(journal_id, user, session=db)
    chapter = await db_unique(
        select(DbChapter).filter_by(
            journal_id=journal.id,
            start_date=body.start_date
        )
    )
    if chapter:
        return BadRequest('Already exists')
    new_chapter = DbChapter(
        start_date=body.start_date,
        end_date=body.start_date + journal.chapter_interval,
        journal=journal
    )
    db.add(new_chapter)
    await db.commit()
    return Chapter.from_orm(new_chapter)


@router.delete('/{journal_id}/chapters/{chapter_id}')
async def delete_chapter(journal_id: int,
                         chapter_id: int,
                         user: User = Depends(CurrentUser),
                         db=Depends(get_db)):
    chapter = await query_chapter(
        journal_id,
        user,
        session=db,
        id=chapter_id
    )
    await db.delete(chapter)
    await db.commit()
    return OK('OK')
