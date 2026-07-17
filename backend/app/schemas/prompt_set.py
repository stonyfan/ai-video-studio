"""prompt_set schemas"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator


# content_yaml 最大 256KB（防误粘贴撑爆 DB / 客户端写盘）
MAX_CONTENT_YAML_BYTES = 256 * 1024


class PromptSetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str | None = Field(None, max_length=255)
    content_yaml: str = Field(..., min_length=1, max_length=512 * 1024)  # Pydantic 字符长度上限
    is_default: bool = False
    is_active: bool = True

    @field_validator("content_yaml")
    @classmethod
    def validate_yaml_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_CONTENT_YAML_BYTES:
            raise ValueError(f"content_yaml 不得超过 {MAX_CONTENT_YAML_BYTES} 字节（256KB）")
        return v


class PromptSetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=255)
    content_yaml: str | None = Field(None, min_length=1, max_length=512 * 1024)
    is_default: bool | None = None
    is_active: bool | None = None
    # 乐观锁：服务端校验 expected_version != current.version → 409
    expected_version: int | None = None

    @field_validator("content_yaml")
    @classmethod
    def validate_yaml_size(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if len(v.encode("utf-8")) > MAX_CONTENT_YAML_BYTES:
            raise ValueError(f"content_yaml 不得超过 {MAX_CONTENT_YAML_BYTES} 字节（256KB）")
        return v


class PromptSetOut(BaseModel):
    id: int
    name: str
    description: str | None
    content_yaml: str
    version: int
    is_default: bool
    is_active: bool
    deleted_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptSetSummary(BaseModel):
    """列表/分配下拉用（不含 content_yaml）"""
    id: int
    name: str
    description: str | None
    version: int
    is_default: bool
    is_active: bool
    bound_user_count: int = 0
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptSetUserOut(BaseModel):
    """用户端 /prompts/me 返回结构（精简）"""
    id: int
    name: str
    version: int
    content_yaml: str

    model_config = {"from_attributes": True}


class PromptSetVersionOut(BaseModel):
    """用户端 /prompts/me/version 轻量 polling 用"""
    id: int
    version: int


class PromptSetOptionOut(BaseModel):
    """Phase 12：用户端 /prompts/me/options 返回项（精简版，带 is_current 标记）"""
    id: int
    name: str
    description: str | None = None
    version: int
    is_default: bool = False
    is_current: bool = False  # 客户端高亮当前生效集用

    model_config = {"from_attributes": True}


class PromptSetSelectPayload(BaseModel):
    """Phase 12：用户切换当前 prompt 集的请求体"""
    prompt_set_id: int
