"""Change extra_currencies type to jsonb

Revision ID: 42e034613d08
Revises: 127bef4f183d
Create Date: 2022-04-29 16:40:16.736439

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
from sqlalchemy import orm

revision = '42e034613d08'
down_revision = '127bef4f183d'
branch_labels = None
depends_on = None


def upgrade():
    from sqlalchemy.dialects.postgresql import JSONB

    from balancebot.common.dbmodels.balance import Balance

    session = orm.Session(bind=op.get_bind())

    op.add_column('balance', sa.Column('extra_currencies_jsonb', JSONB, nullable=True))

    class BalanceMigration(Balance):
        extra_currencies_jsonb = sa.Column('extra_currencies_jsonb', JSONB, nullable=True)

    balances = session.query(BalanceMigration).all()
    for balance in balances:
        balance.extra_currencies_jsonb = balance.extra_currencies
    session.commit()

    op.drop_column('balance', 'extra_currencies')
    op.alter_column('balance',
                    column_name='extra_currencies_jsonb',
                    new_column_name='extra_currencies')


def downgrade():
    pass
