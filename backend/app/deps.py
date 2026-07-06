"""依赖注入：current_user / current_session / admin_required"""
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .database import get_db
from .models import User, Session as SessionModel
from .security import decode_token, sha256_hash
from .config import settings


def get_session_token(authorization: str | None = Header(None)) -> str:
    """从 Authorization header 提取 Bearer token"""
    if not authorization:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少 Authorization 头")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authorization 格式错误")
    return authorization.split(" ", 1)[1].strip()


def get_current_session(
    token: str = Depends(get_session_token),
    db: Session = Depends(get_db),
) -> SessionModel:
    """校验 JWT + session 表，返回 Session"""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 无效")

    token_hash = sha256_hash(token)
    session = (
        db.query(SessionModel)
        .filter(SessionModel.token_hash == token_hash, SessionModel.revoked_at.is_(None))
        .first()
    )
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session 已失效，请重新登录")

    # 心跳超时自动失效
    from datetime import datetime, timedelta, timezone
    timeout = datetime.now(timezone.utc) - timedelta(minutes=settings.SESSION_HEARTBEAT_TIMEOUT_MIN)
    if session.last_heartbeat_at.replace(tzinfo=timezone.utc) < timeout:
        session.revoked_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session 心跳超时")

    return session


def get_current_user(
    session: SessionModel = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> User:
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已禁用")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "需要 admin 权限")
    return user
