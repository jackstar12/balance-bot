from fastapi import FastAPI
from asyncio import current_task
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
import dotenv
import os
from flask import Flask

from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import async_scoped_session, AsyncSession

dotenv.load_dotenv()

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
assert SQLALCHEMY_DATABASE_URI


engine = create_engine(
    SQLALCHEMY_DATABASE_URI
)
#
#session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session = scoped_session(maker)

async_maker = sessionmaker(_class=AsyncSession, autocommit=False, autoflush=False, bind=engine)
async_session = async_scoped_session(async_maker, current_task)

Base = declarative_base()

#app = Flask(__name__)
#app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
#db = SQLAlchemy(app=app, session_options={'autoflush': False})

migrate = Migrate()

if __name__ == '__main__':
    print(async_session.commit)
