"""US-017 (M5) — add request_types.slug and backfill the seven seeded rows

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-08-05 10:05:00.000000

The API speaks slugs (`hardware_devices`); the table only stored display names
("Hardware & Devices") and prefixes. Until now the two were bridged by the
hardcoded REQUEST_TYPE_TO_PREFIX dict in app/schemas/request.py, which M4
deletes — so the slug has to live in the database instead.

Note: this file deliberately does NOT import anything from app/. A migration
must keep working even after the application code around it changes, so the
slug rule is repeated here instead of imported.

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The seven rows created by scripts/seed_request_type.py, keyed on prefix.
# Prefix is used as the key rather than name because it is the one column that
# has been unique and unchanged since the table was created.
SEEDED_SLUGS = {
    "HD": "hardware_devices",
    "SA": "software_access",
    "WF": "workplace_facilities",
    "HR": "human_resources",
    "FT": "financial_travel",
    "SC": "security_compliance",
    "O":  "other",
}


def upgrade() -> None:
    # Added as nullable first: an existing table cannot gain a NOT NULL column
    # in one step, because the rows already there would have nothing in it.
    op.add_column('request_types', sa.Column('slug', sa.String(length=100), nullable=True))

    conn = op.get_bind()

    for prefix, slug in SEEDED_SLUGS.items():
        conn.execute(
            sa.text("UPDATE request_types SET slug = :slug WHERE prefix = :prefix"),
            {"slug": slug, "prefix": prefix},
        )

    # Any row that is not one of the seven (added by hand on some environment)
    # gets a slug derived from its name, exactly the way the service does it.
    leftovers = conn.execute(
        sa.text("SELECT id, name FROM request_types WHERE slug IS NULL")
    ).fetchall()
    for row in leftovers:
        slug = re.sub(r"[^a-z0-9]+", "_", row.name.lower()).strip("_")
        conn.execute(
            sa.text("UPDATE request_types SET slug = :slug WHERE id = :id"),
            {"slug": slug, "id": row.id},
        )

    # Now that every row has a value, the constraints can go on.
    op.alter_column('request_types', 'slug', existing_type=sa.String(length=100), nullable=False)
    op.create_unique_constraint('uq_request_types_slug', 'request_types', ['slug'])


def downgrade() -> None:
    op.drop_constraint('uq_request_types_slug', 'request_types', type_='unique')
    op.drop_column('request_types', 'slug')