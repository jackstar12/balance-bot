from typing import Optional

from sqlalchemy import create_engine, MetaData
from sqlalchemy.orm import sessionmaker, scoped_session, Session, declarative_base

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
