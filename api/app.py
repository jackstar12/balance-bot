from api.database import db, app


def run():
    db.init_app(app)
    db.create_all(app=app)
