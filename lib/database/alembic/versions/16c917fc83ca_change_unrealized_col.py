"""change unrealized col

Revision ID: 16c917fc83ca
Revises: 3e73e9ecc90e
Create Date: 2022-12-26 22:29:23.056131

"""
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy import update
from sqlalchemy.orm import Session

from database.dbmodels import Balance

# revision identifiers, used by Alembic.
revision = '16c917fc83ca'
down_revision = '3e73e9ecc90e'
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())

    op.execute(
        update(Balance).values(
            unrealized=Balance.unrealized - Balance.realized
        )
    )

    pass


def downgrade():
    session = Session(bind=op.get_bind())
    pass
