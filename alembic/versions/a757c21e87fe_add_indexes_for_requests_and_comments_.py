"""add indexes for requests and comments query performance (IT35-331)

Revision ID: a757c21e87fe
Revises: b2c3d4e5f6a7
Create Date: 2026-08-08 00:18:11.595687

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a757c21e87fe'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_comments_author_id'), 'comments', ['author_id'], unique=False)
    op.create_index(op.f('ix_comments_request_id'), 'comments', ['request_id'], unique=False)
    op.create_index(op.f('ix_requests_status'), 'requests', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_requests_status'), table_name='requests')
    op.drop_index(op.f('ix_comments_request_id'), table_name='comments')
    op.drop_index(op.f('ix_comments_author_id'), table_name='comments')