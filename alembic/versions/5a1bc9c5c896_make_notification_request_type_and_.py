"""make notification request_type and status_change_date not null

Revision ID: 5a1bc9c5c896
Revises: 41eb565d6f90
Create Date: 2026-07-27 10:59:38.683235

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a1bc9c5c896'
down_revision: Union[str, None] = '41eb565d6f90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """IT35-281 follow-up — the OpenAPI contract marks both fields required, and
    app/schemas/notification.py types them as required too, but 41eb565d6f90
    created them nullable. A NULL row therefore made GET /notifications and
    PATCH /notifications/{id}/read return 500.

    The table is empty on every environment (nothing calls create_notification()
    yet), so the two backfills below are a safety net rather than a real data
    migration — they exist so this still runs cleanly if a row ever did sneak in.
    """
    op.execute(
        "UPDATE notifications SET request_type = 'other' WHERE request_type IS NULL"
    )
    op.execute(
        "UPDATE notifications SET status_change_date = created_at "
        "WHERE status_change_date IS NULL"
    )

    op.alter_column(
        'notifications',
        'request_type',
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.alter_column(
        'notifications',
        'status_change_date',
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def downgrade() -> None:
    """Back to nullable. The backfilled values are left in place — they are valid
    data, and there is no way to tell them apart from values written normally."""
    op.alter_column(
        'notifications',
        'status_change_date',
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column(
        'notifications',
        'request_type',
        existing_type=sa.String(length=100),
        nullable=True,
    )
