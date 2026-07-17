"""auth 路由：登录/退出/心跳/refresh"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Session as SessionModel
from ..schemas.auth import (
    LoginRequest, TokenResponse, RefreshRequest, RefreshResponse,
    HeartbeatResponse, UserPublic,
)
from ..schemas.user import UserOut
from ..security import (
    verify_password, hash_password,
    create_access_token, create_refresh_token, decode_token, sha256_hash,
)
from ..config import settings
from ..deps import get_current_user, get_current_session


router = APIRouter()


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """登录 + 单点顶替（按 session_type 隔离：同 user 同 type 互踢，跨 type 共存）"""
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已禁用")
    if not user.is_license_valid():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "授权已过期")

    # 单点顶替：只撤同 user + 同 session_type 的活跃 session
    db.query(SessionModel).filter(
        SessionModel.user_id == user.id,
        SessionModel.session_type == payload.session_type,
        SessionModel.revoked_at.is_(None),
    ).update({"revoked_at": datetime.utcnow()})
    db.commit()

    # 生成新 session
    access = create_access_token(user.id, extra={"fp": payload.device_fp or ""})
    refresh = create_refresh_token(user.id)
    session = SessionModel(
        user_id=user.id,
        token_hash=sha256_hash(access),
        device_fp=payload.device_fp,
        ip=request.client.host if request.client else None,
        user_agent=payload.user_agent,
        session_type=payload.session_type,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return TokenResponse(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserPublic.model_validate(user),
    )


@router.post("/logout")
def logout(
    session: SessionModel = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """退出（撤销当前 session）"""
    session.revoked_at = datetime.utcnow()
    db.commit()
    return {"ok": True}


@router.post("/heartbeat", response_model=HeartbeatResponse)
def heartbeat(
    user: User = Depends(get_current_user),
    session: SessionModel = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    """心跳：更新时间 + 检查 license"""
    session.last_heartbeat_at = datetime.utcnow()
    db.commit()

    if not user.is_license_valid():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "授权已过期")

    return HeartbeatResponse(
        ok=True, session_valid=True, license_active=True,
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(payload: RefreshRequest, db: Session = Depends(get_db)):
    """刷新 access token"""
    data = decode_token(payload.refresh_token)
    if not data or data.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh_token 无效")

    user_id = int(data["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不可用")
    if not user.is_license_valid():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "授权已过期")

    access = create_access_token(user.id)

    # 续期：把该用户最新 active session 的 token_hash 更新成新 access token 的 hash
    # 否则后续 /auth/heartbeat 校验 token_hash 时找不到匹配行 → 401 "session 已失效"
    new_hash = sha256_hash(access)
    latest = (
        db.query(SessionModel)
        .filter(SessionModel.user_id == user_id, SessionModel.revoked_at.is_(None))
        .order_by(SessionModel.created_at.desc())
        .first()
    )
    if latest:
        latest.token_hash = new_hash
        latest.last_heartbeat_at = datetime.utcnow()
        db.commit()

    return RefreshResponse(access_token=access, expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.get("/me", response_model=UserPublic)
def me(user: User = Depends(get_current_user)):
    return user
