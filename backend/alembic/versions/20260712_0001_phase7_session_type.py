"""phase7: sessions 加 session_type 字段（desktop / web 隔离）

Revision ID: 0004_phase7_session_type
Revises: 0003_phase6_audit_logs
Create Date: 2026-07-12 00:01:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0004_phase7_session_type"
down_revision: Union[str, None] = "0003_phase6_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 加字段（存量 session 全部归为 desktop，保持兼容）
    op.add_column(
        "sessions",
        sa.Column(
            "session_type",
            sa.String(length=16),
            nullable=False,
            server_default="desktop",
        ),
    )
    # 新增组合索引（包含 session_type）。
    # 不 drop 旧的 idx_user_active：MySQL 因 user_id FK 占用不允许 drop。
    # 旧索引仍可用于 FK 查找；新索引用于 session_type 过滤。
    op.create_index(
        "idx_user_type_active",
        "sessions",
        ["user_id", "session_type", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_user_type_active", table_name="sessions")
    op.drop_column("sessions", "session_type")
