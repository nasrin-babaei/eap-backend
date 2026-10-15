"""add cancellation_date to requests

Revision ID: 6e15cf0d3481
Revises: b27ca4eee2ae
Create Date: ...

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '6e15cf0d3481'
down_revision: Union[str, None] = 'b27ca4eee2ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requests',
        sa.Column('cancellation_date', sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column('requests', 'cancellation_date')