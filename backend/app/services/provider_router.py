"""Provider 路由：选 key + 调上游 + 计费。

把"如何调每个 provider"集中到这里，方便后续扩展（如非 OpenAI 兼容的 provider）。
"""
from __future__ import annotations

import logging
import random
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from ..config import settings
from ..models import ProviderKey, ModelUsage
from . import crypto


log = logging.getLogger("app.services.provider_router")


# Provider → (默认 base_url, 价格表元/千 token)
# 价格表与 video_worker/providers/*.py 保持一致
PROVIDER_DEFAULTS: dict[str, dict[str, Any]] = {
    "qwen-vl": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "pricing": {
            "qwen-vl-plus": {"input": 0.008, "output": 0.008},
            "qwen-vl-max": {"input": 0.020, "output": 0.020},
            "qwen2.5-vl-72b-instruct": {"input": 0.008, "output": 0.008},
            "qwen2.5-vl-7b-instruct": {"input": 0.002, "output": 0.002},
        },
        "default_pricing": {"input": 0.008, "output": 0.008},
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "pricing": {
            "glm-4v-plus": {"input": 0.010, "output": 0.050},
            "glm-4v": {"input": 0.050, "output": 0.050},
            "glm-4v-flash": {"input": 0.0, "output": 0.0},
        },
        "default_pricing": {"input": 0.010, "output": 0.050},
    },
    "doubao": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "pricing": {
            "doubao-1.5-vision-pro": {"input": 0.003, "output": 0.003},
            "doubao-vision-pro": {"input": 0.003, "output": 0.003},
            "doubao-vision-lite": {"input": 0.001, "output": 0.001},
        },
        "default_pricing": {"input": 0.003, "output": 0.003},
    },
}


def pick_active_key(db: Session, provider: str) -> ProviderKey | None:
    """选一个 active key（随机选，平摊负载）。返回 None 表示无可用 key。"""
    keys = (
        db.query(ProviderKey)
        .filter(ProviderKey.provider == provider, ProviderKey.is_active.is_(True))
        .all()
    )
    if not keys:
        return None
    chosen = random.choice(keys)
    chosen.last_used_at = datetime.utcnow()
    db.commit()
    return chosen


def get_base_url(provider: str, key: ProviderKey) -> str:
    """优先用 key 自带的 base_url；否则用 provider 默认"""
    if key.base_url:
        return key.base_url.rstrip("/")
    return PROVIDER_DEFAULTS[provider]["base_url"].rstrip("/")


def get_api_key(key: ProviderKey) -> str:
    """解密 api_key"""
    return crypto.decrypt(key.api_key_encrypted)


def compute_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    """按 provider 价格表估算成本（元）"""
    pricing = PROVIDER_DEFAULTS.get(provider, {}).get("pricing", {})
    p = pricing.get(model) or PROVIDER_DEFAULTS.get(provider, {}).get("default_pricing", {"input": 0, "output": 0})
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1000


def record_usage(
    db: Session,
    *,
    user_id: int,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    status: str,
    error_message: str | None = None,
    latency_ms: int | None = None,
    estimated_cost_cny: float | None = None,
) -> None:
    """写一条 model_usage 记录。失败不抛异常（只 log）。"""
    try:
        if estimated_cost_cny is None:
            estimated_cost_cny = compute_cost(provider, model, input_tokens, output_tokens)
        db.add(ModelUsage(
            user_id=user_id,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_cny=estimated_cost_cny,
            status=status,
            error_message=error_message[:255] if error_message else None,
            latency_ms=latency_ms,
        ))
        db.commit()
    except Exception as e:
        log.warning("record_usage failed: %s", e)
        db.rollback()
