"""model usage schemas"""
from datetime import datetime
from pydantic import BaseModel


class ModelUsageOut(BaseModel):
    id: int
    user_id: int
    username: str | None = None       # join 出来便于展示
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    estimated_cost_cny: float
    status: str
    error_message: str | None
    latency_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ModelUsageSummary(BaseModel):
    """Dashboard 聚合：按时间窗口 + 按 provider"""
    window: str                       # "today" / "7d" / "all"
    total_requests: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_cny: float
    error_count: int
    rate_limited_count: int
    by_provider: list[dict]           # [{provider, requests, tokens, cost, errors}]
