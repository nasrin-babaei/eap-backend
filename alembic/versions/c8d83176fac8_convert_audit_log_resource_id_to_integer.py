"""convert audit_log resource_id to integer
Revision ID: c8d83176fac8
Revises: 01d74579f787
Create Date: 2026-07-12 09:33:19.326699
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8d83176fac8'
down_revision: Union[str, None] = '01d74579f787'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE audit_log "
        "ALTER COLUMN resource_id TYPE INTEGER "
        "USING resource_id::integer"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE audit_log "
        "ALTER COLUMN resource_id TYPE VARCHAR(100) "
        "USING resource_id::varchar"
    )
