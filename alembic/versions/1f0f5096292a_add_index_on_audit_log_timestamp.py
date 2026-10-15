"""add index on audit_log timestamp

Revision ID: 1f0f5096292a
Revises: 5a1bc9c5c896
Create Date: 2026-08-03 16:52:29.842705

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1f0f5096292a'
down_revision: Union[str, None] = '5a1bc9c5c896'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_audit_log_timestamp'), 'audit_log', ['timestamp'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_audit_log_timestamp'), table_name='audit_log')