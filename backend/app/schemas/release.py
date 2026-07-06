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


class ReleaseUpdate(BaseModel):
    is_active: bool | None = None
    release_notes: str | None = None


class ReleaseOut(BaseModel):
    id: int
    version: str
    download_url: str
    sha256: str
    min_supported: str
    release_notes: str | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UpdateCheckResponse(BaseModel):
    has_update: bool
    latest_version: str | None = None
    download_url: str | None = None
    sha256: str | None = None
    release_notes: str | None = None
    min_supported: str | None = None
    current_deprecated: bool = False  # 当前版本低于 min_supported
