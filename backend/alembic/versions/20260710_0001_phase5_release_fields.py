"""phase5: client_releases 加 4 字段（rollout_percentage / force_upgrade / rolled_back_at / grace_hours）

Revision ID: 0002_phase5_release_fields
Revises: 0001_baseline
Create Date: 2026-07-10 00:01:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002_phase5_release_fields"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "client_releases",
        sa.Column(
            "rollout_percentage",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )
    op.add_column(
        "client_releases",
        sa.Column(
            "force_upgrade",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "client_releases",
        sa.Column("rolled_back_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "client_releases",
        sa.Column(
            "grace_hours",
            sa.Integer(),
            nullable=False,
            server_default="24",
        ),
    )


def downgrade() -> None:
    op.drop_column("client_releases", "grace_hours")
    op.drop_column("client_releases", "rolled_back_at")
    op.drop_column("client_releases", "force_upgrade")
    op.drop_column("client_releases", "rollout_percentage")
