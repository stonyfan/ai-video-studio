"""admin 管理云端 provider API key"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ProviderKey, User
from ..schemas.provider_key import (
    ProviderKeyCreate, ProviderKeyUpdate, ProviderKeyOut, ProviderKeyTestResult,
)
from ..services import crypto, provider_router
from ..deps import require_admin


router = APIRouter()


def _to_out(k: ProviderKey) -> ProviderKeyOut:
    """ORM → Out（mask api_key）"""
    try:
        plain = crypto.decrypt(k.api_key_encrypted)
        masked = crypto.mask(plain)
    except Exception:
        masked = "<无法解密>"
    return ProviderKeyOut(
        id=k.id,
        provider=k.provider,
        name=k.name,
        api_key_masked=masked,
        base_url=k.base_url,
        is_active=k.is_active,
        last_used_at=k.last_used_at,
        created_at=k.created_at,
        updated_at=k.updated_at,
    )


@router.get("", response_model=list[ProviderKeyOut])
def list_keys(
    provider: str | None = Query(None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(ProviderKey)
    if provider:
        q = q.filter(ProviderKey.provider == provider)
    rows = q.order_by(ProviderKey.id.desc()).all()
    return [_to_out(k) for k in rows]


@router.post("", response_model=ProviderKeyOut, status_code=status.HTTP_201_CREATED)
def create_key(
    payload: ProviderKeyCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    k = ProviderKey(
        provider=payload.provider,
        name=payload.name,
        api_key_encrypted=crypto.encrypt(payload.api_key),
        base_url=payload.base_url,
        is_active=payload.is_active,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    return _to_out(k)


@router.patch("/{key_id}", response_model=ProviderKeyOut)
def update_key(
    key_id: int,
    payload: ProviderKeyUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    k = db.query(ProviderKey).filter(ProviderKey.id == key_id).first()
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key 不存在")
    if payload.name is not None:
        k.name = payload.name
    if payload.base_url is not None:
        k.base_url = payload.base_url
    if payload.is_active is not None:
        k.is_active = payload.is_active
    db.commit()
    db.refresh(k)
    return _to_out(k)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_key(
    key_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    k = db.query(ProviderKey).filter(ProviderKey.id == key_id).first()
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key 不存在")
    db.delete(k)
    db.commit()


@router.post("/{key_id}/test", response_model=ProviderKeyTestResult)
async def test_key(
    key_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """发一个最小请求验证 key 是否可用"""
    import time
    import httpx

    k = db.query(ProviderKey).filter(ProviderKey.id == key_id).first()
    if not k:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "key 不存在")
    if k.provider not in provider_router.PROVIDER_DEFAULTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "未知 provider")

    base_url = provider_router.get_base_url(k.provider, k)
    try:
        api_key = crypto.decrypt(k.api_key_encrypted)
    except Exception as e:
        return ProviderKeyTestResult(ok=False, message=f"解密失败: {e}")

    # 极简 chat 请求（只为验证 key；多数 provider 不接受空 messages 但能返回 401）
    body = {
        "model": "test",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            upstream = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=body,
            )
    except httpx.HTTPError as e:
        return ProviderKeyTestResult(
            ok=False, message=f"网络错误: {e}",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    latency_ms = int((time.monotonic() - t0) * 1000)
    # 401/403 = key 无效；其他错误（400 模型名错误等）= key 有效但请求格式不对
    if upstream.status_code in (401, 403):
        return ProviderKeyTestResult(
            ok=False, status_code=upstream.status_code,
            message=f"key 被拒绝（{upstream.status_code}）",
            latency_ms=latency_ms,
        )
    # 2xx 或 4xx（除 401/403）都视为 key 本身有效
    return ProviderKeyTestResult(
        ok=True, status_code=upstream.status_code,
        message=f"key 可用（上游 {upstream.status_code}）",
        latency_ms=latency_ms,
    )
