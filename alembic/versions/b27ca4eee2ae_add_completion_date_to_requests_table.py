"""add completion_date to requests table

Revision ID: b27ca4eee2ae
Revises: c8d83176fac8
Create Date: 2026-07-12 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b27ca4eee2ae'
down_revision: Union[str, None] = 'c8d83176fac8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "requests",
        sa.Column("completion_date", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("requests", "completion_date")
