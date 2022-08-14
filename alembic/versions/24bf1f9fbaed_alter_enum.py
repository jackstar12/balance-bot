"""alter enum

Revision ID: 24bf1f9fbaed
Revises: b260b2f5d99b
Create Date: 2022-07-13 20:31:46.296420

"""
from alembic import op
import sqlalchemy as sa
import tradealpha

# revision identifiers, used by Alembic.
revision = '24bf1f9fbaed'
down_revision = 'b260b2f5d99b'
branch_labels = None
depends_on = None

name = 'journaltype'
tmp_name = 'tmp_' + name

old_options = ('CLIENTS', 'MANUAl')
new_options = ('MANUAL', 'INTERVAL')

new_type = sa.Enum(*new_options, name=name)
old_type = sa.Enum(*old_options, name=name)

tcr = sa.sql.table('testcaseresult',
                   sa.Column('status', new_type, nullable=False))

def upgrade():
    op.execute('ALTER TYPE ' + name + ' RENAME TO ' + tmp_name)

    new_type.create(op.get_bind())
    op.execute(f'ALTER TABLE journal ALTER COLUMN type TYPE {name} USING type::text::{name}')
    op.execute('DROP TYPE ' + tmp_name)



def downgrade():
    pass
