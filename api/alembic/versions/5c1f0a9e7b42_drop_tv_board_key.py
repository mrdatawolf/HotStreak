"""drop the TV board key: the board is public now, so the key no longer grants anything

Revision ID: 5c1f0a9e7b42
Revises: e48701b157c7
Create Date: 2026-11-20

"""
from typing import Sequence, Union

from alembic import op


revision: str = '5c1f0a9e7b42'
down_revision: Union[str, Sequence[str], None] = 'e48701b157c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM settings WHERE key = 'board_key'")


def downgrade() -> None:
    # The key was a random secret; there's nothing to restore.
    pass
