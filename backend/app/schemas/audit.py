"""audit log schemas"""
from datetime import datetime
from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: int
    actor_user_id: int
    actor_username: str
    action: str
    target_type: str | None
    target_id: str | None
    target_snapshot: str | None
    ip: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
