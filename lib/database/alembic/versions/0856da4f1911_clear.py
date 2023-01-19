"""clear

Revision ID: 0856da4f1911
Revises: 16c917fc83ca
Create Date: 2023-01-19 14:15:59.463988

"""
from alembic import op
from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.dbmodels import Client, Balance
from database.dbmodels.trade import Trade
from database.dbmodels.transfer import Transfer

# revision identifiers, used by Alembic.
revision = '0856da4f1911'
down_revision = '16c917fc83ca'
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())
    for client in session.query(Client):
        client.last_execution_sync = None
        client.last_transfer_sync = None
    session.execute(delete(Trade))
    session.execute(delete(Balance))
    session.execute(delete(Transfer))


def downgrade():
    session = Session(bind=op.get_bind())
    pass
