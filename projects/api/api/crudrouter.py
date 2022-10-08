from typing import Type, Callable

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, Update, Delete

from api.dependencies import get_db
from api.users import CurrentUser
from api.utils.responses import OK, NotFound
from common.dbasync import db_all, db_unique, TEager
from common.dbmodels.user import User
from common.dbsync import Base
from common.models import BaseModel, OrmBaseModel

TStmt = Select | Update | Delete


def create_crud_router(prefix: str,
                       table: Type[Base],
                       read_schema: Type[OrmBaseModel],
                       create_schema: Type[BaseModel],
                       update_schema: Type[BaseModel] = None,
                       add_filters: Callable[[TStmt, User], Select | Update | Delete] = None,
                       eager_loads: list[TEager] = None,
                       dependencies: list = None):
    def default_filter(stmt: TStmt, user: User) -> Select:
        if hasattr(table, 'user_id'):
            return stmt.where(
                table.user_id == user.id
            )
        return stmt

    eager = eager_loads or []

    if not add_filters:
        add_filters = default_filter

    update_schema = update_schema or create_schema

    router = APIRouter(
        tags=[prefix],
        prefix=prefix,
        dependencies=dependencies
    )

    def read_one(entity_id: int, user: User, db: AsyncSession, **kwargs):
        return db_unique(
            add_filters(
                select(table).where(
                    table.id == entity_id
                ),
                user,
                **kwargs
            ),
            *eager,
            session=db
        )

    def read_all(user: User, db: AsyncSession, **kwargs):
        return db_all(
            add_filters(select(table), user, **kwargs),
            *eager,
            session=db
        )

    @router.post('/', response_model=read_schema)
    async def create(body: create_schema,
                     user: User = Depends(CurrentUser),
                     db: AsyncSession = Depends(get_db),
                     **kwargs):
        instance = table(**body.dict())
        if hasattr(instance, 'user'):
            instance.user = user
        db.add(instance)
        await db.commit()
        return read_schema.from_orm(instance)

    @router.delete('/{entity_id}')
    async def delete_one(entity_id: int,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db),
                         **kwargs):
        entity = await read_one(entity_id, user, db, **kwargs)
        if entity:
            await db.delete(entity)
            await db.commit()
            return OK('Deleted')
        else:
            return NotFound('Invalid id')

    @router.get('/', response_model=list[read_schema])
    async def get_all(user: User = Depends(CurrentUser),
                      db: AsyncSession = Depends(get_db),
                      **kwargs):
        results = await read_all(user, db, **kwargs)

        return OK(
            detail='OK',
            result=[
                read_schema.from_orm(entity)
                for entity in results
            ]
        )

    @router.get('/{entity_id}', response_model=read_schema)
    async def get_one(entity_id: int,
                      user: User = Depends(CurrentUser),
                      db: AsyncSession = Depends(get_db),
                      **kwargs):
        entity = await read_one(entity_id, user, db, **kwargs)

        if entity:
            return read_schema.from_orm(entity)
        else:
            return NotFound('Invalid id')

    @router.patch('/{entity_id}', response_model=read_schema)
    async def update_one(entity_id: int,
                         body: update_schema,
                         user: User = Depends(CurrentUser),
                         db: AsyncSession = Depends(get_db),
                         **kwargs):
        entity = await read_one(entity_id, user, db, **kwargs)

        if entity:
            for key, value in body.dict(exclude_none=True).items():
                setattr(entity, key, value)

            await db.commit()

            return read_schema.from_orm(entity)
        else:
            return NotFound('Invalid id')

    return router
