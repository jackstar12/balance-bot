from fastapi import FastAPI
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine
import dotenv
import os

from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

dotenv.load_dotenv()

app = FastAPI()
app.config['DEBUG'] = False

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
assert SQLALCHEMY_DATABASE_URI

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

engine = create_engine(
    SQLALCHEMY_DATABASE_URI
)

session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

db = SQLAlchemy(app=app, session_options={'autoflush': False})

migrate = Migrate()
