"""add approver_id to requests table

Revision ID: 6aee3e73b198
Revises: 9c52ce1a7dbe
Create Date: 2026-06-15 10:38:52.024041

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = '6aee3e73b198'
down_revision: Union[str, None] = '9c52ce1a7dbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='requests' AND column_name='approver_id'"
    ))
    if not result.fetchone():
        op.add_column('requests', sa.Column('approver_id', sa.Integer(), nullable=True))
        op.create_foreign_key(None, 'requests', 'users', ['approver_id'], ['id'])


def downgrade() -> None:
    op.drop_constraint(None, 'requests', type_='foreignkey')
    op.drop_column('requests', 'approver_id')