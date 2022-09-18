import asyncio
from sqlalchemy import create_engine, MetaData
import dotenv
import os
import aioredis
from sqlalchemy.orm import sessionmaker, scoped_session, Session, declarative_base

dotenv.load_dotenv()

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
assert SQLALCHEMY_DATABASE_URI

engine = create_engine(
    f'postgresql://{SQLALCHEMY_DATABASE_URI}'
)
maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session: Session = scoped_session(maker)

Base = declarative_base()
Meta = MetaData()
