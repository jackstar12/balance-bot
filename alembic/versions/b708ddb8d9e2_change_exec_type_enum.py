"""change exec type enum

Revision ID: b708ddb8d9e2
Revises: 51a41a3b280a
Create Date: 2022-09-05 13:18:29.369201

"""
from alembic import op
import sqlalchemy as sa
import tradealpha


# revision identifiers, used by Alembic.
revision = 'b708ddb8d9e2'
down_revision = '51a41a3b280a'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TYPE exectype RENAME VALUE 'LIQ' TO 'liquidation'")


def downgrade():
    op.execute("ALTER TYPE exectype RENAME VALUE 'liquidation' TO 'misc'")

