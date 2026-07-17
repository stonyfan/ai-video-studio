"""users 加 phone / email / display_name（选填）

Revision ID: 0006_user_contact_fields
Revises: 0005_phase7_provider_usage
Create Date: 2026-07-13 00:01:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_user_contact_fields"
down_revision: Union[str, None] = "0005_phase7_provider_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("display_name", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "display_name")
    op.drop_column("users", "email")
    op.drop_column("users", "phone")
