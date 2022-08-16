from datetime import timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, update, insert
from sqlalchemy.ext.asyncio import AsyncSession

from tradealpha.api.models.template import TemplateUpdate, TemplateInfo, TemplateCreate
from tradealpha.api.dependencies import CurrentUser, get_messenger, CurrentUserDep, get_db
from tradealpha.api.models.completejournal import (
    JournalCreate, JournalInfo, DetailedChapter, JournalUpdate,
    ChapterInfo, ChapterCreate, ChapterUpdate, JournalDetailedInfo
)
from tradealpha.api.utils.responses import BadRequest, OK, CustomJSONResponse, NotFound
from tradealpha.common.dbasync import async_session, db_unique, db_all, db_del_filter
from tradealpha.common.dbmodels.chapter import Chapter as DbChapter
from tradealpha.common.dbmodels.client import add_client_filters, Client
from tradealpha.common.dbmodels.journal import Journal, JournalType
from tradealpha.common.dbmodels.user import User
from tradealpha.common.dbmodels.template import Template as DbTemplate

router = APIRouter(
    tags=["template"],
    dependencies=[Depends(CurrentUser), Depends(get_messenger), Depends(get_db)],
    responses={
        401: {'detail': 'Wrong Email or Password'},
        400: {'detail': "Email is already used"}
    },
)


async def query_templates(template_ids: list[int],
                          user: User,
                          *eager,
                          session: AsyncSession,
                          raise_not_found=True,
                          **filters):
    func = db_unique if len(template_ids) == 1 else db_all
    template = await func(
        select(DbTemplate).filter(
            DbTemplate.id.in_(template_ids) if template_ids else True,
            DbTemplate.user_id == user.id
        ).filter_by(
            **filters
        ),
        session=session,
        *eager
    )
    if not template and raise_not_found:
        raise HTTPException(404, 'Chapter not found')
    return template


@router.post('/template', response_model=TemplateInfo)
async def create_template(body: TemplateCreate,
                          user: User = Depends(CurrentUser),
                          db: AsyncSession = Depends(get_db)):
    template = DbTemplate(
        title=body.title,
        user=user
    )

    db.add(template)
    await db.commit()

    if body.journal_id:
        await db.execute(
            update(Journal).where(
                Journal.id == body.journal_id,
                Journal.user_id == user.id
            ).values(
                default_template_id=template.id
            )
        )

    await db.commit()
    return TemplateInfo.from_orm(template)


@router.get('/template/{template_id}', response_model=TemplateInfo)
async def get_template(template_id: int,
                       user: User = Depends(CurrentUser),
                       db: AsyncSession = Depends(get_db)):
    template = await query_templates([template_id],
                                     user,
                                     session=db)

    return TemplateInfo.from_orm(template)


@router.get('/template', response_model=list[TemplateInfo])
async def get_templates(user: User = Depends(CurrentUser),
                        db: AsyncSession = Depends(get_db)):
    templates = await query_templates([],
                                      user=user,
                                      session=db,
                                      raise_not_found=False)

    return CustomJSONResponse(
        content=jsonable_encoder(TemplateInfo.from_orm(template) for template in (templates or []))
    )


@router.patch('/template/{template_id}')
async def update_template(template_id: int,
                          body: TemplateUpdate,
                          user: User = Depends(CurrentUser),
                          db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        update(DbTemplate).where(
            DbTemplate.id == template_id,
            DbTemplate.user_id == user.id
        ).values(
            **body.dict(exclude_none=True)
        )
    )
    await db.commit()

    if result.rowcount == 0:
        return NotFound('Invalid template id')

    return OK('Updated')


@router.delete('/template/{template_id}')
async def delete_template(template_id: int,
                          user: User = Depends(CurrentUser),
                          db: AsyncSession = Depends(get_db)):
    result = await db_del_filter(
        DbTemplate,
        id=template_id, user_id=user.id,
        session=db
    )
    await db.commit()

    if result.rowcount == 0:
        return NotFound('Invalid template id')

    return OK('Deleted')
