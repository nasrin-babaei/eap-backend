"""add index on requests user_id and created_at

Revision ID: 9c52ce1a7dbe
Revises: 5e387d017212
Create Date: 2026-06-14

"""
from alembic import op

revision = '9c52ce1a7dbe'
down_revision = '5e387d017212'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        'ix_requests_user_id',
        'requests',
        ['user_id']
    )
    op.create_index(
        'ix_requests_created_at',
        'requests',
        ['created_at']
    )


def downgrade() -> None:
    op.drop_index('ix_requests_user_id', table_name='requests')
    op.drop_index('ix_requests_created_at', table_name='requests')