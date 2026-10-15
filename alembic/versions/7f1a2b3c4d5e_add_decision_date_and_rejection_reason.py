"""add decision_date and rejection_reason to requests

Revision ID: 7f1a2b3c4d5e
Revises: 6aee3e73b198
Create Date: ...

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = '7f1a2b3c4d5e'
down_revision: Union[str, None] = '6aee3e73b198'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='requests' AND column_name='decision_date'"
    ))
    if not result.fetchone():
        op.add_column('requests', sa.Column('decision_date', sa.DateTime(timezone=True), nullable=True))

    result = conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='requests' AND column_name='rejection_reason'"
    ))
    if not result.fetchone():
        op.add_column('requests', sa.Column('rejection_reason', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('requests', 'rejection_reason')
    op.drop_column('requests', 'decision_date')