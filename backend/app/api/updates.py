"""客户端更新 + admin 版本管理"""
import hashlib
import logging
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ClientRelease, User
from ..schemas.release import (
    ReleaseCreate, ReleaseUpdate, ReleaseOut, UpdateCheckResponse,
)
from ..deps import require_admin
from ..services.rollout import is_in_rollout

log = logging.getLogger("app.api.updates")


router = APIRouter()
admin_router = APIRouter()


def _parse_version(v: str) -> tuple[int, int, int]:
    """0.3.1 → (0, 3, 1)"""
    parts = v.split(".")
    if len(parts) != 3:
        return (0, 0, 0)
    try:
        return tuple(int(p) for p in parts)  # type: ignore
    except ValueError:
        return (0, 0, 0)


@router.get("/check", response_model=UpdateCheckResponse)
def check_update(
    request: Request,
    current_version: str = Query(..., pattern=r"^\d+\.\d+\.\d+$"),
    platform: str = Query("windows"),
    device_fp: str = Header(None, alias="X-Device-FP"),
    db: Session = Depends(get_db),
):
    """客户端启动时调：是否有新版本。

    算法：
    1. force_upgrade 优先：扫所有 active + force_upgrade=True + version > cur 的 release，
       取最新一条 → current_deprecated=True（即使有更高版本也只指到 target）
    2. 灰度：按 release_id desc 遍历 active releases，用 is_in_rollout 过滤，
       第一条 version > cur 命中的就是推荐版本
    3. 兜底 has_update=False

    device_fp 缺失时用 client IP sha256 兜底，记 warning（兼容老客户端）。
    """
    # device_fp 兜底
    if not device_fp:
        client_ip = request.client.host if request.client else "unknown"
        device_fp = hashlib.sha256(client_ip.encode()).hexdigest()
        log.warning("check_update: 缺少 X-Device-FP header，用 client IP sha256 兜底")

    cur = _parse_version(current_version)

    active_releases = (
        db.query(ClientRelease)
        .filter(ClientRelease.is_active.is_(True))
        .order_by(ClientRelease.id.desc())
        .all()
    )

    # === 1. force_upgrade 优先 ===
    force_targets = [
        r for r in active_releases
        if r.force_upgrade and _parse_version(r.version) > cur
    ]
    if force_targets:
        # 取 version 最高的（force_upgrade 列表里 id desc 已排好，但可能多版本都标了，
        # 取 version 最高更明确）
        target = max(force_targets, key=lambda r: _parse_version(r.version))
        # 推荐版本就是强制目标版本（不管灰度），并标 current_deprecated
        return UpdateCheckResponse(
            has_update=True,
            latest_version=target.version,
            download_url=target.download_url,
            sha256=target.sha256,
            release_notes=target.release_notes,
            min_supported=target.min_supported,
            current_deprecated=True,
            force_upgrade=True,
            grace_hours=target.grace_hours,
        )

    # === 2. 灰度命中扫描 ===
    for r in active_releases:
        if _parse_version(r.version) <= cur:
            continue
        if not is_in_rollout(device_fp, r.id, r.rollout_percentage):
            continue
        # 命中：返回这一条
        # current_deprecated 由 min_supported 判断（兼容老逻辑）
        min_sup = _parse_version(r.min_supported)
        return UpdateCheckResponse(
            has_update=True,
            latest_version=r.version,
            download_url=r.download_url,
            sha256=r.sha256,
            release_notes=r.release_notes,
            min_supported=r.min_supported,
            current_deprecated=cur < min_sup,
            force_upgrade=False,
            grace_hours=r.grace_hours,
        )

    # === 3. 兜底 ===
    # 没有可用更新；但仍要算 current_deprecated（min_supported 跨所有 active releases 取最低）
    if active_releases:
        min_min_sup = min(_parse_version(r.min_supported) for r in active_releases)
        return UpdateCheckResponse(
            has_update=False,
            latest_version=None,
            current_deprecated=cur < min_min_sup,
        )

    return UpdateCheckResponse(has_update=False, latest_version=None)


@router.get("/releases/{version}", response_model=ReleaseOut)
def get_release(version: str, db: Session = Depends(get_db)):
    rel = db.query(ClientRelease).filter(ClientRelease.version == version).first()
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "版本不存在")
    return rel


# === Phase 11: 升级成功上报（客户端新版本首次启动时调） ===

class UpgradeReport(BaseModel):
    from_version: str | None = None  # 老版本（用于排查升级路径）
    to_version: str                  # 新版本 = ClientRelease.version


@router.post("/report-upgrade", status_code=status.HTTP_204_NO_CONTENT)
def report_upgrade(
    payload: UpgradeReport,
    device_fp: str = Header(None, alias="X-Device-FP"),
    db: Session = Depends(get_db),
):
    """客户端 install() 完成后，新版本首次启动时调一次。

    无鉴权（新装后 session 可能未恢复）。device_fp 兜底防滥用。
    幂等性靠客户端：install() 前写 pending_upgrade_report，上报后立即清，不重试。
    """
    rel = db.query(ClientRelease).filter(
        ClientRelease.version == payload.to_version
    ).first()
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "版本不存在")
    rel.upgrade_success_count = (rel.upgrade_success_count or 0) + 1
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# === admin ===

@admin_router.get("", response_model=list[ReleaseOut])
def list_releases(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return db.query(ClientRelease).order_by(ClientRelease.id.desc()).limit(limit).offset(offset).all()


@admin_router.post("", response_model=ReleaseOut, status_code=status.HTTP_201_CREATED)
def create_release(
    payload: ReleaseCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.query(ClientRelease).filter(ClientRelease.version == payload.version).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "版本号已存在")
    rel = ClientRelease(**payload.model_dump())
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return rel


@admin_router.patch("/{release_id}", response_model=ReleaseOut)
def update_release(
    release_id: int,
    payload: ReleaseUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rel = db.query(ClientRelease).filter(ClientRelease.id == release_id).first()
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "版本不存在")
    if payload.is_active is not None:
        # is_active 从 True 改 False → 自动填 rolled_back_at（视为回滚）
        if rel.is_active and not payload.is_active and rel.rolled_back_at is None:
            from datetime import datetime
            rel.rolled_back_at = datetime.utcnow()
        rel.is_active = payload.is_active
    if payload.release_notes is not None:
        rel.release_notes = payload.release_notes
    if payload.rollout_percentage is not None:
        rel.rollout_percentage = payload.rollout_percentage
    if payload.force_upgrade is not None:
        rel.force_upgrade = payload.force_upgrade
    if payload.grace_hours is not None:
        rel.grace_hours = payload.grace_hours
    db.commit()
    db.refresh(rel)
    return rel


@admin_router.post("/{release_id}/rollback", response_model=ReleaseOut)
def rollback_release(
    release_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """一键回滚：is_active=False + rolled_back_at=now()。

    幂等：重复调用不刷新 rolled_back_at。
    """
    rel = db.query(ClientRelease).filter(ClientRelease.id == release_id).first()
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "版本不存在")
    if not rel.is_active:
        # 已回滚 — 不改时间戳（便于追溯首次回滚时间）
        return rel
    from datetime import datetime
    rel.is_active = False
    rel.rolled_back_at = datetime.utcnow()
    db.commit()
    db.refresh(rel)
    return rel
