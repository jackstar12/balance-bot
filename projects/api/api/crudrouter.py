from dataclasses import dataclass, field
from typing import Type, Callable, Optional

from fastapi import APIRouter, Depends
from fastapi_users.types import DependencyCallable
from pydantic.fields import Undefined
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select, Update, Delete

from api.dependencies import get_db
from api.users import CurrentUser
from api.utils.responses import OK, NotFound, BadRequest
from database.dbasync import db_all, db_unique, TEager
from database.dbmodels.user import User
from database.dbsync import Base
from database.models import BaseModel, OrmBaseModel, CreateableModel, InputID

TStmt = Select | Update | Delete


@dataclass
class Route:
    add_filters: Callable[[TStmt, User], Select | Update | Delete] = None
    eager_loads: list[TEager] = field(default_factory=lambda: [])
    user_dependency: DependencyCallable = CurrentUser
    dependencies: list[Depends] = field(default_factory=lambda: [])


def add_crud_routes(router: APIRouter,
                    table: Type[Base],
                    read_schema: Type[OrmBaseModel],
                    create_schema: Type[CreateableModel],
                    update_schema: Type[BaseModel] = None,
                    default_route: Route = None,
                    **routes: dict[str, Route]):
    def default_filter(stmt: TStmt, user: User) -> Select:
        return stmt.where(
            table.user_id == user.id
        )

    if not default_route:
        default_route = Route()

    if not default_route.add_filters:
        default_route.add_filters = default_filter

    update_schema = update_schema or create_schema

    create_route = routes.get('create', default_route)
    if create_route != Undefined:
        @router.post('', response_model=read_schema, dependencies=create_route.dependencies)
        async def create(body: create_schema,
                         user: User = Depends(create_route.user_dependency),
                         db: AsyncSession = Depends(get_db)):
            instance = body.get(user)
            if hasattr(instance, 'user'):
                instance.user = user
            try:
                await instance.validate()
            except (ValueError, AssertionError) as e:
                raise BadRequest(detail=str(e))
            db.add(instance)
            await db.commit()
            return read_schema.from_orm(instance)

    get_one_route = routes.get('get_one', default_route)

    def read_one(entity_id: InputID, user: User, db: AsyncSession, **kwargs):
        return db_unique(
            get_one_route.add_filters(
                select(table).where(
                    table.id == entity_id
                ),
                user,
                **kwargs
            ),
            *get_one_route.eager_loads,
            session=db
        )

    if get_one_route != Undefined:
        @router.get('/{entity_id}', response_model=read_schema, dependencies=get_one_route.dependencies)
        async def get_one(entity_id: InputID,
                          user: User = Depends(get_one_route.user_dependency),
                          db: AsyncSession = Depends(get_db)):
            entity = await read_one(entity_id, user, db)

            if entity:
                return read_schema.from_orm(entity)
            else:
                raise NotFound('Invalid id')

    delete_one_route = routes.get('delete_one', default_route)

    if delete_one_route != Undefined:
        @router.delete('/{entity_id}', dependencies=delete_one_route.dependencies)
        async def delete_one(entity_id: InputID,
                             user: User = Depends(delete_one_route.user_dependency),
                             db: AsyncSession = Depends(get_db)):
            entity = await read_one(entity_id, user, db)
            if entity:
                await db.delete(entity)
                await db.commit()
                return OK('Deleted')
            else:
                raise NotFound('Invalid id')

    all_route = routes.get('get_all', default_route)

    def read_all(user: User, db: AsyncSession, **kwargs):
        return db_all(
            all_route.add_filters(select(table), user, **kwargs),
            *all_route.eager_loads,
            session=db
        )

    if all_route != Undefined:
        @router.get('', response_model=list[read_schema], dependencies=all_route.dependencies)
        async def get_all(user: User = Depends(all_route.user_dependency),
                          db: AsyncSession = Depends(get_db)):
            results = await read_all(user, db)

            return OK(
                detail='OK',
                result=[
                    read_schema.from_orm(entity)
                    for entity in results
                ]
            )

    update_one_route = routes.get('update_one', default_route)
    if update_one_route != Undefined:
        @router.patch('/{entity_id}', response_model=read_schema, dependencies=update_one_route.dependencies)
        async def update_one(entity_id: InputID,
                             body: update_schema,
                             user: User = Depends(update_one_route.user_dependency),
                             db: AsyncSession = Depends(get_db)):
            entity = await read_one(entity_id, user, db)

            if entity:
                for key, value in body.dict(exclude_none=True).items():
                    setattr(entity, key, value)
                try:
                    await entity.validator()
                except (AssertionError, ValueError) as e:
                    raise BadRequest(detail=str(e))

                await db.commit()

                return read_schema.from_orm(entity)
            else:
                raise NotFound('Invalid id')

    return router


