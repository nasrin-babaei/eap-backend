"""create requests and request_types tables
Revision ID: b413e5f82231
Revises: a7c1ae533453
Create Date: 2026-06-11 18:41:03.311786
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b413e5f82231'
down_revision: Union[str, None] = 'a7c1ae533453'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('request_types',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('is_active', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('approver_id', sa.Integer(), nullable=True),
    sa.Column('request_type_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('justification', sa.Text(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'approved', 'rejected', 'completed', 'cancelled', name='request_status'),
                              nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
    sa.ForeignKeyConstraint(['request_type_id'], ['request_types.id']),
    sa.ForeignKeyConstraint(['approver_id'], ['users.id']),
    sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('requests')
    op.drop_table('request_types')