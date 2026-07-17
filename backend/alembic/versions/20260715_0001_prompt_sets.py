"""phase10: 新增 prompt_sets 表 + users.prompt_set_id + 默认集种子

Revision ID: 0008_prompt_sets
Revises: 0007_phase8_error_reports
Create Date: 2026-07-15 00:01:00
"""
from typing import Sequence, Union
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision: str = "0008_prompt_sets"
down_revision: Union[str, None] = "0007_phase8_error_reports"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# 默认集 YAML 文件路径（打包到镜像内 backend/app/data/）
DEFAULT_YAML_PATH = Path(__file__).resolve().parents[2] / "app" / "data" / "prompts_default.yaml"


def upgrade() -> None:
    # 1. 建 prompt_sets 表
    op.create_table(
        "prompt_sets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("content_yaml", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # 2. users 加 prompt_set_id 字段（FK ON DELETE SET NULL，删 set 后用户走默认）
    op.add_column(
        "users",
        sa.Column(
            "prompt_set_id",
            sa.BigInteger(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_users_prompt_set_id",
        "users",
        "prompt_sets",
        ["prompt_set_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_users_prompt_set_id", "users", ["prompt_set_id"], unique=False)

    # 3. 种子默认集（从 backend/app/data/prompts_default.yaml 读，插入 is_default=True）
    bind = op.get_bind()
    yaml_text = DEFAULT_YAML_PATH.read_text(encoding="utf-8")
    bind.execute(
        sa.text(
            "INSERT INTO prompt_sets (name, description, content_yaml, version, is_default, is_active) "
            "VALUES (:name, :desc, :yaml, 1, 1, 1)"
        ),
        {
            "name": "默认",
            "desc": "系统默认 prompt 集（随版本分发）",
            "yaml": yaml_text,
        },
    )


def downgrade() -> None:
    op.drop_index("ix_users_prompt_set_id", table_name="users")
    op.drop_constraint("fk_users_prompt_set_id", "users", type_="foreignkey")
    op.drop_column("users", "prompt_set_id")
    op.drop_table("prompt_sets")
