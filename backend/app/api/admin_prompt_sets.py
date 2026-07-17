"""admin 管理 prompt 集（CRUD + duplicate）"""
from datetime import datetime
from typing import Annotated
import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import require_admin
from ..models import PromptSet, User
from ..schemas.prompt_set import (
    PromptSetCreate, PromptSetUpdate, PromptSetOut, PromptSetSummary,
)


router = APIRouter()


def _validate_yaml(content: str) -> None:
    """YAML 必须能 safe_load + 含 templates.triplet_detect.default"""
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"YAML 解析失败：{e}",
        )
    if not isinstance(data, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "YAML 顶层必须是 mapping（dict）",
        )
    templates = data.get("templates")
    if not isinstance(templates, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "缺少 templates 段",
        )
    triplet = templates.get("triplet_detect")
    if not isinstance(triplet, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "缺少 templates.triplet_detect 段",
        )
    if "default" not in triplet or not triplet["default"]:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "templates.triplet_detect.default 不能为空",
        )


def _bound_user_count(db: Session, ps_id: int) -> int:
    return db.query(User).filter(User.prompt_set_id == ps_id).count()


def _to_summary(db: Session, ps: PromptSet) -> PromptSetSummary:
    return PromptSetSummary(
        id=ps.id,
        name=ps.name,
        description=ps.description,
        version=ps.version,
        is_default=ps.is_default,
        is_active=ps.is_active,
        bound_user_count=_bound_user_count(db, ps.id),
        updated_at=ps.updated_at,
    )


@router.get("", response_model=list[PromptSetSummary])
def list_prompt_sets(
    include_deleted: bool = Query(False),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    q = db.query(PromptSet)
    if not include_deleted:
        q = q.filter(PromptSet.deleted_at.is_(None))
    rows = q.order_by(PromptSet.is_default.desc(), PromptSet.id.asc()).all()
    return [_to_summary(db, ps) for ps in rows]


@router.post("", response_model=PromptSetOut, status_code=status.HTTP_201_CREATED)
def create_prompt_set(
    payload: PromptSetCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _validate_yaml(payload.content_yaml)
    # is_default=True → 单事务内把其他全部置 false
    if payload.is_default:
        db.query(PromptSet).filter(
            PromptSet.deleted_at.is_(None),
            PromptSet.is_default.is_(True),
        ).update({PromptSet.is_default: False}, synchronize_session=False)
    ps = PromptSet(
        name=payload.name,
        description=payload.description,
        content_yaml=payload.content_yaml,
        version=1,
        is_default=payload.is_default,
        is_active=payload.is_active,
    )
    db.add(ps)
    db.commit()
    db.refresh(ps)
    return ps


@router.get("/{ps_id}", response_model=PromptSetOut)
def get_prompt_set(
    ps_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ps = db.query(PromptSet).filter(
        PromptSet.id == ps_id,
        PromptSet.deleted_at.is_(None),
    ).first()
    if not ps:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt 集不存在")
    return ps


@router.patch("/{ps_id}", response_model=PromptSetOut)
def update_prompt_set(
    ps_id: int,
    payload: PromptSetUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ps = db.query(PromptSet).filter(
        PromptSet.id == ps_id,
        PromptSet.deleted_at.is_(None),
    ).first()
    if not ps:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt 集不存在")

    # 乐观锁
    if payload.expected_version is not None and payload.expected_version != ps.version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"版本已变（当前 v{ps.version}），请刷新后重试",
        )

    # 普通字段
    if payload.name is not None:
        ps.name = payload.name
    if payload.description is not None:
        ps.description = payload.description
    if payload.is_active is not None:
        ps.is_active = payload.is_active

    # content_yaml 变更 → 校验 + version+1
    if payload.content_yaml is not None and payload.content_yaml != ps.content_yaml:
        _validate_yaml(payload.content_yaml)
        ps.content_yaml = payload.content_yaml
        ps.version += 1

    # is_default 切换：单事务内先把其他全部置 false
    if payload.is_default is True and not ps.is_default:
        db.query(PromptSet).filter(
            PromptSet.id != ps_id,
            PromptSet.deleted_at.is_(None),
            PromptSet.is_default.is_(True),
        ).update({PromptSet.is_default: False}, synchronize_session=False)
        ps.is_default = True
    elif payload.is_default is False and ps.is_default:
        # 不允许把默认集降级为非默认（否则没有默认集了）
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "请先把其他集设为默认（不能直接取消当前默认集的默认状态）",
        )

    db.commit()
    db.refresh(ps)
    return ps


@router.delete("/{ps_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt_set(
    ps_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    ps = db.query(PromptSet).filter(
        PromptSet.id == ps_id,
        PromptSet.deleted_at.is_(None),
    ).first()
    if not ps:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "prompt 集不存在")
    if ps.is_default:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "不能删除默认集（请先把其他集设为默认）",
        )
    bound = _bound_user_count(db, ps_id)
    if bound > 0:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"仍有 {bound} 个用户绑定此集，请先解绑",
        )
    ps.deleted_at = datetime.utcnow()
    ps.is_active = False
    db.commit()


@router.post("/{ps_id}/duplicate", response_model=PromptSetOut, status_code=status.HTTP_201_CREATED)
def duplicate_prompt_set(
    ps_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """复制现有集为新集（name 带「(副本)」后缀，is_default=False，version 重置为 1）"""
    src = db.query(PromptSet).filter(
        PromptSet.id == ps_id,
        PromptSet.deleted_at.is_(None),
    ).first()
    if not src:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "源 prompt 集不存在")
    new_ps = PromptSet(
        name=f"{src.name}(副本)",
        description=src.description,
        content_yaml=src.content_yaml,
        version=1,
        is_default=False,
        is_active=True,
    )
    db.add(new_ps)
    db.commit()
    db.refresh(new_ps)
    return new_ps
