"""create audit_log table (EAP-IT35)

Revision ID: a7c1ae533453
Revises: f083f245d20b
Create Date: 2026-06-01 12:18:34.077572

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1ae533453'
down_revision: Union[str, None] = 'f083f245d20b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id",            sa.Integer(),   nullable=False),
        sa.Column("user_id",       sa.Integer(),   nullable=True),
        sa.Column("action",        sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50),  nullable=True),
        sa.Column("resource_id",   sa.Integer(),   nullable=True),
        sa.Column("ip_address",    sa.String(45),  nullable=True),
        sa.Column("timestamp",     sa.DateTime(),  nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_id"),
        "audit_log",
        ["id"],
        unique=False
    )
def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_id"), table_name="audit_log")
    op.drop_table("audit_log")
