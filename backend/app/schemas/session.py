"""session schemas（admin 端用）"""
from datetime import datetime
from pydantic import BaseModel


class SessionOut(BaseModel):
    id: int
    user_id: int
    username: str | None     # join 出来，便于展示
    token_hash: str          # 截断显示用
    device_fp: str | None
    ip: str | None
    user_agent: str | None
    session_type: str
    created_at: datetime
    last_heartbeat_at: datetime
    revoked_at: datetime | None

    model_config = {"from_attributes": True}
