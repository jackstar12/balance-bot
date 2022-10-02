from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.routers.template import query_templates
from tradealpha.api.dependencies import get_messenger, get_db
from tradealpha.api.users import CurrentUser, get_current_user
from tradealpha.api.models.completejournal import (
    JournalCreate, JournalInfo, DetailedChapter, JournalUpdate,
    ChapterCreate, ChapterUpdate, JournalDetailedInfo
)
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse
from tradealpha.common.dbasync import db_unique, db_all
from tradealpha.common.dbmodels.editing.chapter import Chapter as DbChapter
from tradealpha.common.dbmodels.client import add_client_filters, Client
from tradealpha.common.dbmodels.editing.journal import Journal, JournalType
from tradealpha.common.dbmodels.user import User

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
        select(Journal).where(
            Journal.id == journal_id,
            Journal.user_id == user.id
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
            user
        ),
        session=db_session
    )
    if len(clients) != len(client_ids):
        raise HTTPException(status_code=404, detail='Invalid client IDs')
    return clients


@router.post('')
async def create_journal(body: JournalCreate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    clients = await query_clients(body.client_ids, user, db)
    if len(clients) != len(body.client_ids):
        return BadRequest(detail='Invalid client IDs')
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



@router.get(
    '',
    description="Query all the users journals",
    response_model=List[JournalInfo]
)
async def get_journals(user: User = Depends(get_current_user(User.journals))):
    return CustomJSONResponse(
        content=jsonable_encoder(
            [
                JournalInfo.from_orm(journal)
                for journal in user.journals
            ]
        )
    )


@router.get('/{journal_id}', response_model=JournalDetailedInfo)
async def get_journal(journal_id: int,
                      user: User = Depends(CurrentUser),
                      db: AsyncSession = Depends(get_db)):
    journal = await query_journal(
        journal_id, user,
        (Journal.chapters, [DbChapter.children]),
        Journal.default_template,
        Journal.clients,
        session=db
    )

    await journal.update(db)

    return JournalDetailedInfo.from_orm(journal)


@router.patch('/{journal_id}', response_model=JournalDetailedInfo)
async def update_journal(journal_id: int,
                         body: JournalUpdate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(
        journal_id,
        user,
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
async def delete_journal(journal_id: int, user: User = Depends(CurrentUser), db: AsyncSession = Depends(get_db)):
    journal = await query_journal(journal_id, user, session=db)
    if journal:
        await db.delete(journal)
        await db.commit()
    return OK('Deleted')


@router.get('/{journal_id}/chapter/{chapter_id}')
async def get_chapter(journal_id: int, chapter_id: int, user: User = Depends(CurrentUser),
                      db: AsyncSession = Depends(get_db)):
    chapter = await query_chapter(
        journal_id,
        user,
        # DbChapter.trades,
        session=db,
        id=chapter_id
    )

    return DetailedChapter.from_orm(chapter)


@router.get('/{journal_id}/chapter/{chapter_id}/data')
async def get_chapter_data(journal_id: int, chapter_id: int, user: User = Depends(CurrentUser),
                      db: AsyncSession = Depends(get_db)):
    chapter = await query_chapter(
        journal_id,
        user,
        # DbChapter.trades,
        DbChapter.balances,
        session=db,
        id=chapter_id
    )

    await DbChapter.all_childs(chapter.id, db)

    return DetailedChapter.from_orm(chapter)



@router.patch('/{journal_id}/chapter/{chapter_id}')
async def update_chapter(journal_id: int,
                         chapter_id: int,
                         body: ChapterUpdate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    chapter = await query_chapter(
        journal_id,
        user,
        session=db,
        id=chapter_id
    )
    if body.doc is not None:
        chapter.doc = body.doc
    if body.data:
        chapter.data = body.data
    await db.commit()
    return OK('OK')


@router.post('/{journal_id}/chapter', response_model=DetailedChapter)
async def create_chapter(journal_id: int,
                         body: ChapterCreate,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db)):
    journal = await query_journal(journal_id, user, Journal.clients, session=db)

    template = None
    if body.template_id:
        template = await query_templates([body.template_id],
                                         user=user,
                                         session=db)

    new_chapter = journal.create_chapter(body.parent_id, template)

    db.add(new_chapter)
    await db.commit()
    return DetailedChapter.from_orm(new_chapter)


@router.get('/{journal_id}/trades')
async def get_journal_trades(journal_id: int,
                             user: User = Depends(CurrentUser),
                             db: AsyncSession = Depends(get_db)):
    journal = await query_journal(journal_id, user, session=db)

    await db_all(
        select(DbChapter.doc['doc']['content']['id']).filter(
            DbChapter.doc['doc']['type'] == 'trade-mention',
            DbChapter.journal_id == journal.id
        )
    )


@router.delete('/{journal_id}/chapter/{chapter_id}')
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
