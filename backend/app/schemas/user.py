"""user admin schemas"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=6, max_length=128)
    license_expires_at: datetime | None = None
    role: str = "user"
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    display_name: str | None = Field(None, max_length=64)


class UserUpdate(BaseModel):
    password: str | None = Field(None, min_length=6, max_length=128)
    license_expires_at: datetime | None = None
    is_active: bool | None = None
    phone: str | None = Field(None, max_length=32)
    email: str | None = Field(None, max_length=255)
    display_name: str | None = Field(None, max_length=64)
    # null = 不改；显式 null（JSON 里传 null 字段）= 解绑走默认
    # 通过 model_fields_set 区分"未传"vs"传 null"
    prompt_set_id: int | None = Field(default=None)
    # Phase 12：admin 分配可选 prompt 集列表
    # 未传 = 不改；显式传 [] = 清空；[1,2,3] = 设为这三套
    prompt_set_option_ids: list[int] | None = Field(default=None)


class ResetPassword(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    phone: str | None
    email: str | None
    display_name: str | None
    license_expires_at: datetime | None
    is_active: bool
    prompt_set_id: int | None
    # Phase 12：admin 给用户分配的可选 prompt 集 id 列表
    prompt_set_option_ids: list[int] = Field(default_factory=list)
    created_at: datetime

    model_config = {"from_attributes": True}
