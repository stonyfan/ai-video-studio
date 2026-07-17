"""Vision model proxy：OpenAI 兼容透传。

POST /api/v1/vision/{provider}/chat/completions
  - {provider} ∈ {qwen-vl, glm, doubao}
  - 透传 body 给上游（OpenAI ChatCompletion 格式）
  - 鉴权: JWT（user 必须 is_active + license_valid）
  - 限速: 每用户每分钟 N 请求 → 超额 429
  - 计费: 写 model_usage 表
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import User
from ..services import rate_limit, provider_router


log = logging.getLogger("app.api.vision")


router = APIRouter()


async def _proxy(
    provider: str,
    body: dict[str, Any],
    user: User,
    db: Session,
) -> dict[str, Any]:
    """通用透传逻辑。"""
    if not settings.VISION_PROXY_ENABLED:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Vision 代理未启用")

    if provider not in provider_router.PROVIDER_DEFAULTS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"不支持的 provider: {provider}")

    # license 校验（admin / 普通用户都要）
    if not user.is_license_valid():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "授权已过期")

    # 限速
    if not rate_limit.check_and_record(user.id):
        provider_router.record_usage(
            db,
            user_id=user.id,
            provider=provider,
            model=str(body.get("model", "")),
            status="rate_limited",
            error_message="rate limit exceeded",
        )
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"请求过于频繁（上限 {settings.VISION_RATE_LIMIT_PER_MIN}/分钟）",
        )

    # 选 key
    key = provider_router.pick_active_key(db, provider)
    if key is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"无可用 {provider} key，请联系 admin 配置",
        )

    base_url = provider_router.get_base_url(provider, key)
    api_key = provider_router.get_api_key(key)
    model_name = str(body.get("model", ""))

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=settings.VISION_UPSTREAM_TIMEOUT_SEC) as client:
            upstream = await client.post(
                f"{base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.HTTPError as e:
        latency = int((time.monotonic() - t0) * 1000)
        provider_router.record_usage(
            db,
            user_id=user.id,
            provider=provider,
            model=model_name,
            status="error",
            error_message=f"upstream network error: {e}",
            latency_ms=latency,
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"上游网络错误: {e}")

    latency = int((time.monotonic() - t0) * 1000)

    # 上游返回非 2xx
    if upstream.status_code >= 400:
        try:
            err_body = upstream.json()
            err_msg = str(err_body)[:255]
        except Exception:
            err_msg = upstream.text[:255]
        provider_router.record_usage(
            db,
            user_id=user.id,
            provider=provider,
            model=model_name,
            status="error",
            error_message=f"upstream {upstream.status_code}: {err_msg}",
            latency_ms=latency,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"上游 {provider} 返回 {upstream.status_code}: {err_msg}",
        )

    # 成功：提取 usage → 计费 → 返回上游 body
    try:
        resp_data = upstream.json()
    except Exception as e:
        provider_router.record_usage(
            db,
            user_id=user.id,
            provider=provider,
            model=model_name,
            status="error",
            error_message=f"invalid json: {e}",
            latency_ms=latency,
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "上游返回非 JSON")

    usage = resp_data.get("usage") or {}
    in_tok = int(usage.get("prompt_tokens", 0) or 0)
    out_tok = int(usage.get("completion_tokens", 0) or 0)

    provider_router.record_usage(
        db,
        user_id=user.id,
        provider=provider,
        model=model_name,
        input_tokens=in_tok,
        output_tokens=out_tok,
        status="success",
        latency_ms=latency,
    )

    return resp_data


@router.post("/{provider}/chat/completions")
async def proxy_chat_completions(
    provider: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """OpenAI 兼容透传"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请求体不是合法 JSON")
    if not isinstance(body, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请求体必须是 JSON 对象")
    return await _proxy(provider, body, user, db)
