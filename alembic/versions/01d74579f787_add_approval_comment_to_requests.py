"""add approval_comment to requests

Revision ID: 01d74579f787
Revises: f976d2ff95d9
Create Date: 2026-07-03 11:24:14.638635

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '01d74579f787'
down_revision: Union[str, None] = 'f976d2ff95d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('requests', sa.Column('approval_comment', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('requests', 'approval_comment')
