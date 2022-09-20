"""change JSON to document type

Revision ID: 2ffbb0bd6229
Revises: 3b5bb49d8a65
Create Date: 2022-07-11 18:55:27.902998

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import tradealpha

# revision identifiers, used by Alembic.
revision = '2ffbb0bd6229'
down_revision = '3b5bb49d8a65'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('journal', 'overview',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=tradealpha.common.dbmodels.types.Document(astext_type=sa.Text()),
               existing_nullable=True)
    op.alter_column('template', 'content',
               existing_type=postgresql.JSON(astext_type=sa.Text()),
               type_=tradealpha.common.dbmodels.types.Document(astext_type=sa.Text()),
               existing_nullable=False)
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('template', 'content',
               existing_type=tradealpha.common.dbmodels.types.Document(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=False)
    op.alter_column('journal', 'overview',
               existing_type=tradealpha.common.dbmodels.types.Document(astext_type=sa.Text()),
               type_=postgresql.JSON(astext_type=sa.Text()),
               existing_nullable=True)
    # ### end Alembic commands ###