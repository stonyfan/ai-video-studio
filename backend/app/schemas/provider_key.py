"""provider key schemas"""
from datetime import datetime
from pydantic import BaseModel, Field


SUPPORTED_PROVIDERS = ("qwen-vl", "glm", "doubao")


class ProviderKeyCreate(BaseModel):
    provider: str = Field(..., pattern=r"^(qwen-vl|glm|doubao)$")
    name: str = Field(..., min_length=1, max_length=64)
    api_key: str = Field(..., min_length=1, max_length=512)
    base_url: str | None = Field(None, max_length=255)
    is_active: bool = True


class ProviderKeyUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    base_url: str | None = Field(None, max_length=255)
    is_active: bool | None = None


class ProviderKeyOut(BaseModel):
    id: int
    provider: str
    name: str
    api_key_masked: str
    base_url: str | None
    is_active: bool
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProviderKeyTestResult(BaseModel):
    ok: bool
    status_code: int | None = None
    message: str
    latency_ms: int | None = None
