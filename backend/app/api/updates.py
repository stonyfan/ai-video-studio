"""客户端更新 + admin 版本管理"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import ClientRelease, User
from ..schemas.release import (
    ReleaseCreate, ReleaseUpdate, ReleaseOut, UpdateCheckResponse,
)
from ..deps import require_admin


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
    current_version: str = Query(..., pattern=r"^\d+\.\d+\.\d+$"),
    platform: str = Query("windows"),
    db: Session = Depends(get_db),
):
    """客户端启动时调：是否有新版本"""
    latest = (
        db.query(ClientRelease)
        .filter(ClientRelease.is_active.is_(True))
        .order_by(ClientRelease.id.desc())
        .first()
    )

    if not latest:
        return UpdateCheckResponse(has_update=False, latest_version=None)

    cur = _parse_version(current_version)
    latest_v = _parse_version(latest.version)
    min_sup = _parse_version(latest.min_supported)

    return UpdateCheckResponse(
        has_update=latest_v > cur,
        latest_version=latest.version,
        download_url=latest.download_url,
        sha256=latest.sha256,
        release_notes=latest.release_notes,
        min_supported=latest.min_supported,
        current_deprecated=cur < min_sup,
    )


@router.get("/releases/{version}", response_model=ReleaseOut)
def get_release(version: str, db: Session = Depends(get_db)):
    rel = db.query(ClientRelease).filter(ClientRelease.version == version).first()
    if not rel:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "版本不存在")
    return rel


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
        rel.is_active = payload.is_active
    if payload.release_notes is not None:
        rel.release_notes = payload.release_notes
    db.commit()
    db.refresh(rel)
    return rel
