"""error_report schemas"""
from datetime import datetime
from pydantic import BaseModel, Field


class ErrorReportOut(BaseModel):
    id: int
    user_id: int
    username: str | None = None  # join users 表
    job_id: str | None
    message: str
    file_size: int
    client_version: str | None
    client_platform: str | None
    status: str
    admin_note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ErrorReportUpdate(BaseModel):
    """admin 修改状态/备注"""
    status: str | None = Field(None, pattern=r"^(open|resolved|ignored)$")
    admin_note: str | None = Field(None, max_length=2000)
