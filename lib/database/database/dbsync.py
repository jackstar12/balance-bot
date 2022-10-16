from typing import Optional

from sqlalchemy import create_engine, MetaData
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker, scoped_session, Session, declarative_base, object_session
import sqlalchemy.orm as orm

from database.env import environment
from database.models import BaseModel


engine = create_engine(
    f'postgresql://{environment.DATABASE_URI}'
)
maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session: Session = scoped_session(maker)

Base = declarative_base()
Meta = MetaData()


class BaseMixin:
    __tablename__: str
    __model__: Optional[BaseModel]
    __realtime__: Optional[bool]

    @property
    def sync_session(self) -> Optional[AsyncSession]:
        return object_session(self)

    @property
    def async_session(self) -> Optional[AsyncSession]:
        return self._sa_instance_state.async_session
