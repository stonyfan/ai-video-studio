"""用户端 prompt 集拉取（客户端登录后 sync 用）"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import PromptSet, User, UserPromptSetOption
from ..schemas.prompt_set import (
    PromptSetOptionOut,
    PromptSetSelectPayload,
    PromptSetUserOut,
    PromptSetVersionOut,
)


router = APIRouter()


def _resolve_prompt_set(user: User, db: Session) -> PromptSet | None:
    """用户绑定的集 → 没绑走默认集（is_default=True 且未软删 + is_active）"""
    if user.prompt_set_id:
        ps = (
            db.query(PromptSet)
            .filter(
                PromptSet.id == user.prompt_set_id,
                PromptSet.deleted_at.is_(None),
                PromptSet.is_active.is_(True),
            )
            .first()
        )
        if ps:
            return ps
    # 兜底默认集
    return (
        db.query(PromptSet)
        .filter(
            PromptSet.is_default.is_(True),
            PromptSet.deleted_at.is_(None),
            PromptSet.is_active.is_(True),
        )
        .first()
    )


def _get_default_set_id(db: Session) -> int | None:
    """当前 is_default 集的 id（不存在返回 None）"""
    row = (
        db.query(PromptSet.id)
        .filter(
            PromptSet.is_default.is_(True),
            PromptSet.deleted_at.is_(None),
            PromptSet.is_active.is_(True),
        )
        .first()
    )
    return row[0] if row else None


@router.get("/me", response_model=PromptSetUserOut)
def get_my_prompts(
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拉取当前用户应使用的 prompt 集（含完整 content_yaml）。

    客户端启动时调，结果缓存本地。
    Cache-Control 30s 避免多 renderer 组件访问打 DB。
    """
    ps = _resolve_prompt_set(user, db)
    if not ps:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "无可用 prompt 集（请联系管理员）",
        )
    response.headers["Cache-Control"] = "private, max-age=30"
    return ps


@router.get("/me/version", response_model=PromptSetVersionOut)
def get_my_prompts_version(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """轻量 polling — 心跳 piggyback 用，只返回 id + version。

    客户端比对本地缓存的版本号，不同则触发完整 sync。
    """
    ps = _resolve_prompt_set(user, db)
    if not ps:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "无可用 prompt 集（请联系管理员）",
        )
    return PromptSetVersionOut(id=ps.id, version=ps.version)


@router.get("/me/options", response_model=list[PromptSetOptionOut])
def list_my_options(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 12：列出当前用户可切换的 prompt 集。

    返回值始终包含 is_default 集和用户当前 prompt_set_id（即使 admin 没显式分配）。
    老用户（options 表为空）也能看到至少 1 个选项。
    """
    # 1. 收集 ids: options 表 ∪ {current_prompt_set_id} ∪ {is_default set id}
    option_ids: set[int] = {
        o.prompt_set_id
        for o in db.query(UserPromptSetOption).filter(
            UserPromptSetOption.user_id == user.id
        ).all()
    }
    if user.prompt_set_id:
        option_ids.add(user.prompt_set_id)
    default_id = _get_default_set_id(db)
    if default_id:
        option_ids.add(default_id)

    if not option_ids:
        return []

    # 2. 查所有可用 prompt_set（默认集排前，再按 id 升序）
    sets = (
        db.query(PromptSet)
        .filter(
            PromptSet.id.in_(option_ids),
            PromptSet.deleted_at.is_(None),
            PromptSet.is_active.is_(True),
        )
        .order_by(PromptSet.is_default.desc(), PromptSet.id.asc())
        .all()
    )

    # 3. 标记当前生效集
    current_id = user.prompt_set_id or default_id
    return [
        PromptSetOptionOut(
            id=s.id,
            name=s.name,
            description=s.description,
            version=s.version,
            is_default=s.is_default,
            is_current=(s.id == current_id),
        )
        for s in sets
    ]


@router.post("/me/select", response_model=PromptSetUserOut)
def select_my_prompt_set(
    payload: PromptSetSelectPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Phase 12：用户切换当前 prompt 集。

    校验：prompt_set_id 在用户的 options 池里 OR 是 is_default 集 OR 是当前已生效集。
    校验：prompt_set 存在 + active + 未软删。
    成功后更新 users.prompt_set_id 并返回新集（客户端拿到后触发 sync）。
    """
    target_id = payload.prompt_set_id
    target = (
        db.query(PromptSet)
        .filter(
            PromptSet.id == target_id,
            PromptSet.deleted_at.is_(None),
            PromptSet.is_active.is_(True),
        )
        .first()
    )
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prompt 集不存在或已停用")

    # 权限校验：必须在 options 池 / 是 is_default / 是当前生效
    allowed_ids: set[int] = {
        o.prompt_set_id
        for o in db.query(UserPromptSetOption).filter(
            UserPromptSetOption.user_id == user.id
        ).all()
    }
    default_id = _get_default_set_id(db)
    if default_id:
        allowed_ids.add(default_id)
    if user.prompt_set_id:
        allowed_ids.add(user.prompt_set_id)
    if target_id not in allowed_ids:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "无权使用此 prompt 集（不在你的可选列表中）",
        )

    user.prompt_set_id = target_id
    db.commit()
    db.refresh(user)

    ps = _resolve_prompt_set(user, db)
    if not ps:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "切换后无可用 prompt 集（请联系管理员）",
        )
    return ps
