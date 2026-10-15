"""create comments table
Revision ID: c8bfd58a09db
Revises: 13262e488be4
Create Date: 2026-06-30 07:50:03.243252
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c8bfd58a09db'
down_revision: Union[str, None] = '13262e488be4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('comments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column("request_id", sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )



def downgrade() -> None:
    op.drop_table('comments')