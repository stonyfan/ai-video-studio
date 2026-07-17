"""phase8: 新增 error_reports 表（用户错误上报）

Revision ID: 0007_phase8_error_reports
Revises: 0006_user_contact_fields
Create Date: 2026-07-14 00:01:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_phase8_error_reports"
down_revision: Union[str, None] = "0006_user_contact_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "error_reports",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("client_version", sa.String(length=32), nullable=True),
        sa.Column("client_platform", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("admin_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_error_reports_user_id", "error_reports", ["user_id"], unique=False)
    op.create_index("ix_error_reports_job_id", "error_reports", ["job_id"], unique=False)
    op.create_index("ix_error_reports_created_at", "error_reports", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_error_reports_created_at", table_name="error_reports")
    op.drop_index("ix_error_reports_job_id", table_name="error_reports")
    op.drop_index("ix_error_reports_user_id", table_name="error_reports")
    op.drop_table("error_reports")
