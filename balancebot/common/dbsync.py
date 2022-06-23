import asyncio
from sqlalchemy import create_engine, MetaData
import dotenv
import os
import aioredis
from sqlalchemy.orm import sessionmaker, scoped_session, Session
from sqlalchemy.ext.declarative import declarative_base

dotenv.load_dotenv()

SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URI')
assert SQLALCHEMY_DATABASE_URI

print(SQLALCHEMY_DATABASE_URI)

engine = create_engine(
    f'postgresql://{SQLALCHEMY_DATABASE_URI}'
)
#
# session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
maker = sessionmaker(autocommit=False, autoflush=False, bind=engine)
session: Session = scoped_session(maker)

Base = declarative_base()
Meta = MetaData()

# app = Flask(__name__)
# app.config['SQLALCHEMY_DATABASE_URI'] = SQLALCHEMY_DATABASE_URI
# db = SQLAlchemy(app=app, session_options={'autoflush': False})

redis = aioredis.Redis()


if __name__ == '__main__':
    print(asyncio.run(redis.get('test')))


