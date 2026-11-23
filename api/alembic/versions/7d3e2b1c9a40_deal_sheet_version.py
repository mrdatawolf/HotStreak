"""deal sheet version

Revision ID: 7d3e2b1c9a40
Revises: 126f96f1c396
Create Date: 2026-11-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7d3e2b1c9a40'
down_revision: Union[str, Sequence[str], None] = '126f96f1c396'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.add_column(sa.Column('sheet_version', sa.String(length=16), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('deals', schema=None) as batch_op:
        batch_op.drop_column('sheet_version')
