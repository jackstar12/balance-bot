from typing import Optional, Any

from sqlalchemy import create_engine, MetaData
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker, scoped_session, Session, declarative_base, object_session
import sqlalchemy.orm as orm

from database.env import ENV
from database.models import BaseModel

engine = create_engine(
    f'postgresql://{ENV.PG_URL}',
    future=True
)
maker = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)
session: Session = scoped_session(maker)


class Base:
    __allow_unmapped__ = True


Base = declarative_base(cls=Base)
Meta = MetaData()


def FKey(column: str,
         onupdate=None,
         ondelete=None,
         **kw):
    split = column.split('.')
    return sa.ForeignKey(column, onupdate=onupdate, ondelete=ondelete, name=fkey_name(split[0], split[1]), **kw)


def fkey_name(tablename: Any, column_name: str):
    return f'{tablename}_{column_name}_fkey'


class BaseMixin:
    __tablename__: str
    __model__: Optional[BaseModel]
    __realtime__: Optional[bool]

    @property
    def sync_session(self) -> Optional[Session]:
        return object_session(self)

    @property
    def async_session(self) -> Optional[AsyncSession]:
        return self._sa_instance_state.async_session

    async def validate(self):
        pass
