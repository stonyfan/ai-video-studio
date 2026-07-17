"""admin 查 model_usage（用量审计）"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ModelUsage, User
from ..schemas.model_usage import ModelUsageOut, ModelUsageSummary
from ..deps import require_admin


router = APIRouter()


@router.get("", response_model=list[ModelUsageOut])
def list_usage(
    user_id: int | None = Query(None),
    provider: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(ModelUsage, User.username).join(User, ModelUsage.user_id == User.id, isouter=True)
    if user_id is not None:
        q = q.filter(ModelUsage.user_id == user_id)
    if provider:
        q = q.filter(ModelUsage.provider == provider)
    if status_filter:
        q = q.filter(ModelUsage.status == status_filter)
    if since:
        q = q.filter(ModelUsage.created_at >= since)
    if until:
        q = q.filter(ModelUsage.created_at <= until)
    rows = q.order_by(ModelUsage.id.desc()).limit(limit).offset(offset).all()
    return [
        ModelUsageOut(
            id=mu.id, user_id=mu.user_id, username=username,
            provider=mu.provider, model=mu.model,
            input_tokens=mu.input_tokens, output_tokens=mu.output_tokens,
            estimated_cost_cny=mu.estimated_cost_cny, status=mu.status,
            error_message=mu.error_message, latency_ms=mu.latency_ms,
            created_at=mu.created_at,
        )
        for mu, username in rows
    ]


@router.get("/summary", response_model=ModelUsageSummary)
def usage_summary(
    window: str = Query("today", pattern=r"^(today|7d|30d|all)$"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """按时间窗口聚合：总数 + 按 provider 分组"""
    now = datetime.utcnow()
    if window == "today":
        since = now - timedelta(hours=24)
    elif window == "7d":
        since = now - timedelta(days=7)
    elif window == "30d":
        since = now - timedelta(days=30)
    else:
        since = None

    q = db.query(ModelUsage)
    if since is not None:
        q = q.filter(ModelUsage.created_at >= since)

    rows = q.all()
    total_in = sum(r.input_tokens for r in rows)
    total_out = sum(r.output_tokens for r in rows)
    total_cost = sum(r.estimated_cost_cny for r in rows)
    error_count = sum(1 for r in rows if r.status == "error")
    rl_count = sum(1 for r in rows if r.status == "rate_limited")

    # by provider
    by_prov: dict[str, dict] = {}
    for r in rows:
        p = r.provider
        if p not in by_prov:
            by_prov[p] = {
                "provider": p,
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "estimated_cost_cny": 0.0,
                "errors": 0,
            }
        by_prov[p]["requests"] += 1
        by_prov[p]["input_tokens"] += r.input_tokens
        by_prov[p]["output_tokens"] += r.output_tokens
        by_prov[p]["estimated_cost_cny"] += r.estimated_cost_cny
        if r.status == "error":
            by_prov[p]["errors"] += 1

    return ModelUsageSummary(
        window=window,
        total_requests=len(rows),
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_cost_cny=round(total_cost, 4),
        error_count=error_count,
        rate_limited_count=rl_count,
        by_provider=list(by_prov.values()),
    )
