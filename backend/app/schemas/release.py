"""client release schemas"""
from datetime import datetime
from pydantic import BaseModel, Field


class ReleaseCreate(BaseModel):
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    download_url: str
    sha256: str = Field(..., min_length=64, max_length=64)
    min_supported: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    release_notes: str | None = None
    is_active: bool = True
    rollout_percentage: int = Field(100, ge=0, le=100)
    force_upgrade: bool = False
    grace_hours: int = Field(24, ge=0, le=720)


class ReleaseUpdate(BaseModel):
    is_active: bool | None = None
    release_notes: str | None = None
    rollout_percentage: int | None = Field(None, ge=0, le=100)
    force_upgrade: bool | None = None
    grace_hours: int | None = Field(None, ge=0, le=720)


class ReleaseOut(BaseModel):
    id: int
    version: str
    download_url: str
    sha256: str
    min_supported: str
    release_notes: str | None
    is_active: bool
    created_at: datetime
    rollout_percentage: int = 100
    force_upgrade: bool = False
    rolled_back_at: datetime | None = None
    grace_hours: int = 24
    # Phase 11: counter 计数（无去重）
    download_count: int = 0
    upgrade_success_count: int = 0

    model_config = {"from_attributes": True}


class UpdateCheckResponse(BaseModel):
    has_update: bool
    latest_version: str | None = None
    download_url: str | None = None
    sha256: str | None = None
    release_notes: str | None = None
    min_supported: str | None = None
    current_deprecated: bool = False  # 当前版本低于 min_supported 或被 force_upgrade
    force_upgrade: bool = False       # 是否触发"必须升级"提示
    grace_hours: int | None = None    # 客户端下载后宽限期
