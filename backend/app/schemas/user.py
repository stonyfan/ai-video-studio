"""user admin schemas"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    password: str = Field(..., min_length=6, max_length=128)
    license_expires_at: datetime | None = None
    role: str = "user"


class UserUpdate(BaseModel):
    password: str | None = Field(None, min_length=6, max_length=128)
    license_expires_at: datetime | None = None
    is_active: bool | None = None


class ResetPassword(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=128)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    license_expires_at: datetime | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
