"""US-017 (M3) — make request_types.is_active a real boolean

Revision ID: a1b2c3d4e5f6
Revises: 1f0f5096292a
Create Date: 2026-08-05 10:00:00.000000

The column was declared as `Column(String, default=True)`: a text column that
holds a boolean. US-017 is built entirely on activating/deactivating a request
type, so the column has to have the type its values pretend to be.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '1f0f5096292a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The existing rows hold the text 'true' (or NULL if a row was inserted
    # without the column). Normalise them BEFORE the cast, otherwise the
    # NOT NULL below would fail on the first NULL row.
    op.execute("UPDATE request_types SET is_active = 'true' WHERE is_active IS NULL")

    # PostgreSQL will not silently reinterpret text as boolean, so we tell it
    # how with USING. 'true'/'false'/'t'/'f'/'1'/'0' all cast correctly.
    op.alter_column(
        'request_types',
        'is_active',
        existing_type=sa.String(),
        type_=sa.Boolean(),
        postgresql_using='is_active::boolean',
        nullable=False,
        server_default=sa.text('true'),
    )


def downgrade() -> None:
    op.alter_column(
        'request_types',
        'is_active',
        existing_type=sa.Boolean(),
        type_=sa.String(),
        postgresql_using='is_active::text',
        nullable=True,
        server_default=None,
    )