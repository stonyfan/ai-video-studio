"""phase11: client_releases 加 download_count + upgrade_success_count

Revision ID: 0009_release_metrics
Revises: 0008_prompt_sets
Create Date: 2026-07-18 00:01:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_release_metrics"
down_revision: Union[str, None] = "0008_prompt_sets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "client_releases",
        sa.Column(
            "download_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "client_releases",
        sa.Column(
            "upgrade_success_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("client_releases", "upgrade_success_count")
    op.drop_column("client_releases", "download_count")
