"""auth schemas"""
from datetime import datetime
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)
    device_fp: str | None = Field(None, max_length=64)
    user_agent: str | None = Field(None, max_length=255)
    session_type: str = Field("desktop", pattern=r"^(desktop|web)$")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int  # 秒
    token_type: str = "bearer"
    user: "UserPublic"


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int


class HeartbeatResponse(BaseModel):
    ok: bool = True
    session_valid: bool = True
    license_active: bool = True


class UserPublic(BaseModel):
    id: int
    username: str
    role: str
    license_expires_at: datetime | None
    is_active: bool

    model_config = {"from_attributes": True}


# 解决前向引用
TokenResponse.model_rebuild()
