"""add index to comments request_id created_at

Revision ID: f976d2ff95d9
Revises: c69c0644def5
Create Date: 2026-07-02 14:36:21.229592

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f976d2ff95d9'
down_revision: Union[str, None] = 'c69c0644def5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_comments_request_id_created_at",
        "comments",
        ["request_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_comments_request_id_created_at",
        table_name="comments",
    )
