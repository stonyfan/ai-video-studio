"""admin sessions 管理：列表 + revoke"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Session as SessionModel
from ..schemas.session import SessionOut
from ..deps import require_admin


router = APIRouter()


def _to_out(s: SessionModel, username: str | None) -> dict:
    """Session ORM → SessionOut dict（带 join 出来的 username）"""
    return {
        "id": s.id,
        "user_id": s.user_id,
        "username": username,
        "token_hash": s.token_hash,
        "device_fp": s.device_fp,
        "ip": s.ip,
        "user_agent": s.user_agent,
        "session_type": s.session_type,
        "created_at": s.created_at,
        "last_heartbeat_at": s.last_heartbeat_at,
        "revoked_at": s.revoked_at,
    }


@router.get("", response_model=list[SessionOut])
def list_sessions(
    user_id: int | None = Query(None),
    active_only: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """列 sessions，默认只看活跃的"""
    q = db.query(SessionModel, User.username).join(User, SessionModel.user_id == User.id, isouter=True)
    if user_id is not None:
        q = q.filter(SessionModel.user_id == user_id)
    if active_only:
        q = q.filter(SessionModel.revoked_at.is_(None))
    rows = (
        q.order_by(SessionModel.last_heartbeat_at.desc())
        .limit(limit).offset(offset).all()
    )
    return [_to_out(s, uname) for s, uname in rows]


@router.post("/{session_id}/revoke", response_model=SessionOut)
def revoke_session(
    session_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """吊销指定 session"""
    s = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session 不存在")
    if s.revoked_at is None:
        s.revoked_at = datetime.utcnow()
        db.commit()
        db.refresh(s)
    user = db.query(User).filter(User.id == s.user_id).first()
    return _to_out(s, user.username if user else None)
