"""phase12: 用户可选 prompt 集（多对多关联表）

Revision ID: 0010_user_prompt_set_options
Revises: 0009_release_metrics
Create Date: 2026-07-20 00:01:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_user_prompt_set_options"
down_revision: Union[str, None] = "0009_release_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_prompt_set_options",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("prompt_set_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_set_id"], ["prompt_sets.id"], ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", "prompt_set_id", name="uq_user_prompt_set"),
    )
    op.create_index("ix_upso_user_id", "user_prompt_set_options", ["user_id"])
    op.create_index("ix_upso_prompt_set_id", "user_prompt_set_options", ["prompt_set_id"])

    # 数据迁移：现有 prompt_set_id 不为 null 的用户，把当前集加入 options 池
    # 老用户即使没显式分配 options，也能在客户端看到/切换自己当前那套
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "INSERT INTO user_prompt_set_options (user_id, prompt_set_id) "
            "SELECT id, prompt_set_id FROM users WHERE prompt_set_id IS NOT NULL"
        )
    )


def downgrade() -> None:
    op.drop_index("ix_upso_prompt_set_id", table_name="user_prompt_set_options")
    op.drop_index("ix_upso_user_id", table_name="user_prompt_set_options")
    op.drop_table("user_prompt_set_options")
