from api.database import db, app, migrate
import config
import api.dbutils
from api.dbmodels.archive import Archive
from api.dbmodels.client import Client
from api.dbmodels.discorduser import DiscordUser
from api.dbmodels.balance import Balance
from api.dbmodels.event import Event

db.init_app(app)
migrate.init_app(app, db)
db.create_all(app=app)


def run():
    db.init_app(app)
    migrate.init_app(app, db)
    db.create_all(app=app)


if __name__ == '__main__':
    run()
