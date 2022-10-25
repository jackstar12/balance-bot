"""reintroduce coin column in transfer

Revision ID: 358424d1dd1c
Revises: 4baacbf738d6
Create Date: 2022-10-25 20:28:51.293973

"""
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy import String, Column, update, delete
from sqlalchemy.orm import Session

from database.dbmodels import Client, Balance, Execution
from database.dbmodels.trade import Trade
from database.dbmodels.transfer import Transfer


# revision identifiers, used by Alembic.
revision = '358424d1dd1c'
down_revision = '4baacbf738d6'
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())
    session.execute(
        update(Client).values(
            last_execution_sync=None,
            last_transfer_sync=None
        )
    )
    session.execute(
        delete(Trade)
    )
    session.execute(
        delete(Balance)
    )
    session.execute(
        delete(Transfer)
    )
    op.add_column('transfer', Column('coin', String, nullable=True))
    pass


def downgrade():
    session = Session(bind=op.get_bind())
    op.drop_column('transfer', 'coin')
    pass
