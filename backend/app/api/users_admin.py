"""admin 用户管理"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PromptSet, User, UserPromptSetOption
from ..schemas.user import UserCreate, UserUpdate, UserOut, ResetPassword
from ..security import hash_password
from ..deps import require_admin


router = APIRouter()


def _user_option_ids(db: Session, user_id: int) -> list[int]:
    """获取用户已分配的 prompt 集 ids（按 id 升序，稳定排序）"""
    rows = (
        db.query(UserPromptSetOption.prompt_set_id)
        .filter(UserPromptSetOption.user_id == user_id)
        .order_by(UserPromptSetOption.id.asc())
        .all()
    )
    return [r[0] for r in rows]


def _user_to_out(user: User, db: Session) -> UserOut:
    """User ORM → UserOut，附带 prompt_set_option_ids"""
    return UserOut(
        id=user.id,
        username=user.username,
        role=user.role,
        phone=user.phone,
        email=user.email,
        display_name=user.display_name,
        license_expires_at=user.license_expires_at,
        is_active=user.is_active,
        prompt_set_id=user.prompt_set_id,
        prompt_set_option_ids=_user_option_ids(db, user.id),
        created_at=user.created_at,
    )


@router.get("", response_model=list[UserOut])
def list_users(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    users = db.query(User).order_by(User.id.desc()).limit(limit).offset(offset).all()
    return [_user_to_out(u, db) for u in users]


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
        phone=payload.phone,
        email=payload.email,
        display_name=payload.display_name,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_to_out(user, db)


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
    # 选填字段：显式传值才更新（None 表示不更新；空字符串表示清空）
    if payload.phone is not None:
        user.phone = payload.phone.strip() or None
    if payload.email is not None:
        user.email = payload.email.strip() or None
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or None
    # prompt_set_id：通过 model_fields_set 区分"未传"vs"传 null"
    if "prompt_set_id" in payload.model_fields_set:
        new_id = payload.prompt_set_id
        if new_id is None:
            user.prompt_set_id = None  # 解绑走默认
        else:
            ps = db.query(PromptSet).filter(
                PromptSet.id == new_id,
                PromptSet.deleted_at.is_(None),
            ).first()
            if not ps:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"prompt 集 #{new_id} 不存在")
            user.prompt_set_id = new_id
    # Phase 12：prompt_set_option_ids（admin 分配可选 prompt 集池）
    if "prompt_set_option_ids" in payload.model_fields_set:
        new_ids = payload.prompt_set_option_ids or []
        # 去重 + 校验所有 id 存在 + 未软删
        new_ids_set = set(new_ids)
        if new_ids_set:
            valid_count = (
                db.query(PromptSet)
                .filter(
                    PromptSet.id.in_(new_ids_set),
                    PromptSet.deleted_at.is_(None),
                )
                .count()
            )
            if valid_count != len(new_ids_set):
                raise HTTPException(
                    status.HTTP_404_NOT_FOUND,
                    "部分 prompt 集 id 不存在或已删除",
                )

        # 差量同步 options 表
        existing = (
            db.query(UserPromptSetOption)
            .filter(UserPromptSetOption.user_id == user.id)
            .all()
        )
        existing_ids = {o.prompt_set_id for o in existing}
        # 删除：existing - new
        for o in existing:
            if o.prompt_set_id not in new_ids_set:
                db.delete(o)
        # 新增：new - existing
        for nid in new_ids_set - existing_ids:
            db.add(UserPromptSetOption(user_id=user.id, prompt_set_id=nid))

        # 如果用户当前 prompt_set_id 不在 new_ids → fallback
        if user.prompt_set_id and user.prompt_set_id not in new_ids_set:
            default_set = (
                db.query(PromptSet)
                .filter(
                    PromptSet.is_default.is_(True),
                    PromptSet.deleted_at.is_(None),
                    PromptSet.is_active.is_(True),
                )
                .first()
            )
            user.prompt_set_id = (
                default_set.id if default_set
                else (new_ids[0] if new_ids else None)
            )
    db.commit()
    db.refresh(user)
    return _user_to_out(user, db)


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
    return _user_to_out(user, db)
