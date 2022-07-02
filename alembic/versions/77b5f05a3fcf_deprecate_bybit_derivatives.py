"""deprecate bybit-derivatives

Revision ID: 77b5f05a3fcf
Revises: becc5951bf45
Create Date: 2022-06-25 14:44:59.830939

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy import update
from sqlalchemy.orm import Session

from tradealpha.common.dbmodels import Client

revision = '77b5f05a3fcf'
down_revision = 'becc5951bf45'
branch_labels = None
depends_on = None


def upgrade():
    db = Session(op.get_bind())
    db.execute(
        update(Client).where(
            Client.exchange == 'bybit-derivatives'
        ).values(
            exchange='bybit-linear'
        )
    )
    db.commit()


def downgrade():
    db = Session(op.get_bind())
    db.execute(
        update(Client).where(
            Client.exchange == 'bybit-linear'
        ).values(
            exchange='bybit-derivatives'
        )
    )
    db.commit()
