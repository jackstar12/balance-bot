"""change platform structure

Revision ID: d1f13f442d97
Revises: f6be99aae636
Create Date: 2022-11-25 18:59:49.137943

"""
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy import update, text
from sqlalchemy.orm import Session



# revision identifiers, used by Alembic.
from database.dbmodels import Event

revision = 'd1f13f442d97'
down_revision = 'f6be99aae636'
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())
    session.execute(
        text("update event set location = jsonb_set(location, '{name}', location->'platform')")
    )
    session.execute(
        text("update event set location = location - 'platform'")
    )
    session.commit()
    pass


def downgrade():
    session = Session(bind=op.get_bind())
    pass
