"""change exec type enum

Revision ID: ac4dc505dd4d
Revises: b708ddb8d9e2
Create Date: 2022-09-05 13:23:57.649250

"""
from enum import Enum

from alembic import op
import sqlalchemy as sa
import tradealpha


# revision identifiers, used by Alembic.
revision = 'ac4dc505dd4d'
down_revision = 'b708ddb8d9e2'
branch_labels = None
depends_on = None


class ExecType(Enum):
    TRADE = "trade"
    TRANSFER = "transfer"
    FUNDING = "funding"
    LIQUIDATION = "liquidation"
    STOP = "stop"
    TP = "tp"


name = 'exectype'
tmp_name = 'tmp_' + name
old_type = sa.Enum(name=name)
new_type = sa.Enum(ExecType, name=name)


def upgrade():
    # Create a tempoary "_status" type, convert and drop the "old" type

    op.execute('ALTER TYPE ' + name + ' RENAME TO ' + tmp_name)

    new_type.create(op.get_bind())
    op.execute('ALTER TABLE execution ALTER COLUMN type ' +
               'TYPE ' + name + ' USING type::text::' + name)
    op.execute('DROP TYPE ' + tmp_name)



def downgrade():
    # Convert 'output_limit_exceeded' status into 'timed_out'
    pass