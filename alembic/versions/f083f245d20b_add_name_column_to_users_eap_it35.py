"""add name column to users (EAP-IT35)

Revision ID: f083f245d20b
Revises: 58b8ab0dbb2e
Create Date: 2026-05-29

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f083f245d20b'
down_revision: Union[str, None] = '58b8ab0dbb2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Önce nullable olarak ekle
    op.add_column('users', sa.Column('name', sa.String(length=255), nullable=True))
    # Mevcut kayıtlara default değer ver
    op.execute("UPDATE users SET name = 'Admin' WHERE name IS NULL")
    # Sonra NOT NULL yap
    op.alter_column('users', 'name', nullable=False)

def downgrade() -> None:
    op.drop_column('users', 'name')
