"""create notifications table

Revision ID: 41eb565d6f90
Revises: 6e15cf0d3481
Create Date: 2026-07-24 16:09:26.558662

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '41eb565d6f90'
down_revision: Union[str, None] = 'b959cb977a55'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('notifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.String(length=20), nullable=False),
        sa.Column('request_type', sa.String(length=100), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('status_change_date', sa.DateTime(timezone=True), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_notifications_user_created', 'notifications', ['user_id', 'created_at'], unique=False)
    op.create_index('ix_notifications_user_is_read', 'notifications', ['user_id', 'is_read'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_notifications_user_is_read', table_name='notifications')
    op.drop_index('ix_notifications_user_created', table_name='notifications')
    op.drop_table('notifications')


