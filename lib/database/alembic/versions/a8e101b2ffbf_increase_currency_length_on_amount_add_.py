"""increase currency length on amount, add joined_at

Revision ID: a8e101b2ffbf
Revises: 6953e25d67fe
Create Date: 2022-11-05 23:01:29.271468

"""
import fastapi_users_db_sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.orm import Session, lazyload

from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
from database.dbmodels import EventEntry

revision = 'a8e101b2ffbf'
down_revision = '6953e25d67fe'
branch_labels = None
depends_on = None


def upgrade():
    session = Session(bind=op.get_bind())
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('amount', 'currency',
               existing_type=sa.VARCHAR(length=3),
               type_=sa.String(length=5),
               existing_nullable=False)
    op.add_column('evententry', sa.Column('joined_at', sa.DateTime(timezone=True), nullable=True))

    for entry in session.query(EventEntry).options(lazyload(EventEntry.event)):
        entry.joined_at = entry.event.start

    session.commit()
    op.alter_column('evententry', 'joined_at', nullable=False)

    # ### end Alembic commands ###


def downgrade():
    session = Session(bind=op.get_bind())
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('evententry', 'joined_at')
    op.alter_column('amount', 'currency',
               existing_type=sa.String(length=5),
               type_=sa.VARCHAR(length=3),
               existing_nullable=False)
    # ### end Alembic commands ###
