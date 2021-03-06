from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
import dotenv
import os
dotenv.load_dotenv()

app = Flask(__name__)
app.config['DEBUG'] = False
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI', 'postgresql://postgres:postgres@localhost:5432/balance-bot')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app=app, session_options={'autoflush': False})
migrate = Migrate()
