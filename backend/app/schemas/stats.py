"""stats schemas（Dashboard）"""
from datetime import datetime
from pydantic import BaseModel


class StatsResponse(BaseModel):
    users_total: int
    users_active: int            # is_active=True
    releases_total: int
    releases_active: int
    sessions_active: int         # revoked_at IS NULL
    recent_audit_count: int      # 最近 24h
    # 监控
    db_size_mb: float            # 数据库占用（MB）
    latest_backup: "BackupInfo | None"  # 最新备份状态


class BackupInfo(BaseModel):
    filename: str
    size_kb: float
    mtime: datetime


StatsResponse.model_rebuild()

