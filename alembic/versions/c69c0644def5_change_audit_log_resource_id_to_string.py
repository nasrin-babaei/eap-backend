"""change audit_log resource_id to string

Revision ID: c69c0644def5
Revises: c8bfd58a09db
Create Date: ...

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c69c0644def5'
down_revision: Union[str, None] = 'c8bfd58a09db'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'audit_log', 'resource_id',
        existing_type=sa.Integer(),
        type_=sa.String(length=100),
        existing_nullable=True,
        postgresql_using='resource_id::text'
    )


def downgrade() -> None:
    op.alter_column(
        'audit_log', 'resource_id',
        existing_type=sa.String(length=100),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using='resource_id::integer'
    )