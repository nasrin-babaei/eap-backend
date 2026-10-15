"""create notifications table (IT35-281)

Revision ID: b959cb977a55
Revises: 6e15cf0d3481
Create Date: 2026-07-24 13:29:02.700350

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b959cb977a55'
down_revision: Union[str, None] = '6e15cf0d3481'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass