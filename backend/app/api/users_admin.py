"""admin 用户管理"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas.user import UserCreate, UserUpdate, UserOut, ResetPassword
from ..security import hash_password
from ..deps import require_admin


router = APIRouter()


@router.get("", response_model=list[UserOut])
def list_users(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return db.query(User).order_by(User.id.desc()).limit(limit).offset(offset).all()


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role=payload.role if payload.role in ("user", "admin") else "user",
        license_expires_at=payload.license_expires_at,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)
    if payload.license_expires_at is not None:
        user.license_expires_at = payload.license_expires_at
    if payload.is_active is not None:
        user.is_active = payload.is_active
    db.commit()
    db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.role == "admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除 admin 账号")
    db.delete(user)
    db.commit()


@router.post("/{user_id}/reset_password", response_model=UserOut)
def reset_password(
    user_id: int,
    payload: ResetPassword,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    db.refresh(user)
    return user
