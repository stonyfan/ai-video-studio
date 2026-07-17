"""admin 管理用户错误上报：列表 / 下载 / 改状态"""
import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import ErrorReport, User
from ..schemas.error_report import ErrorReportOut, ErrorReportUpdate
from ..deps import require_admin


router = APIRouter()


def _to_out(r: ErrorReport, username: str | None) -> ErrorReportOut:
    return ErrorReportOut(
        id=r.id,
        user_id=r.user_id,
        username=username,
        job_id=r.job_id,
        message=r.message,
        file_size=r.file_size,
        client_version=r.client_version,
        client_platform=r.client_platform,
        status=r.status,
        admin_note=r.admin_note,
        created_at=r.created_at,
    )


@router.get("", response_model=list[ErrorReportOut])
def list_reports(
    user_id: int | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """admin 列出错误报告（带过滤 + 分页）"""
    q = db.query(ErrorReport, User.username).join(User, ErrorReport.user_id == User.id, isouter=True)
    if user_id is not None:
        q = q.filter(ErrorReport.user_id == user_id)
    if status_filter:
        q = q.filter(ErrorReport.status == status_filter)
    if since:
        q = q.filter(ErrorReport.created_at >= since)
    if until:
        q = q.filter(ErrorReport.created_at <= until)
    rows = q.order_by(ErrorReport.id.desc()).limit(limit).offset(offset).all()
    return [_to_out(r, username) for r, username in rows]


@router.get("/{report_id}/download")
def download_report(
    report_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """下载错误报告 zip 包"""
    r = db.query(ErrorReport).filter(ErrorReport.id == report_id).first()
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    file_path = os.path.join(settings.ERROR_REPORTS_DIR, r.file_path)
    if not os.path.isfile(file_path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件已丢失（可能已被清理）")
    download_name = f"{r.file_path}"  # 形如 err_u{uid}_{ts}_{rand}.zip
    return FileResponse(
        path=file_path,
        filename=download_name,
        media_type="application/zip",
    )


@router.patch("/{report_id}", response_model=ErrorReportOut)
def update_report(
    report_id: int,
    payload: ErrorReportUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """admin 改状态 / 加备注"""
    r = db.query(ErrorReport).filter(ErrorReport.id == report_id).first()
    if not r:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "报告不存在")
    if payload.status is not None:
        r.status = payload.status
    if payload.admin_note is not None:
        r.admin_note = payload.admin_note.strip() or None
    db.commit()
    db.refresh(r)
    username = db.query(User.username).filter(User.id == r.user_id).scalar()
    return _to_out(r, username)
