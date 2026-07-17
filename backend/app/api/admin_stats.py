"""admin dashboard stats"""
import os
import glob
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, ClientRelease, Session as SessionModel, AuditLog
from ..schemas.stats import StatsResponse, BackupInfo
from ..deps import require_admin


router = APIRouter()

BACKUP_DIR = os.environ.get("BACKUP_DIR", "/backups")


def _get_db_size_mb(db: Session) -> float:
    """查 information_schema 拿当前数据库占用（MB）"""
    try:
        row = db.execute(
            text("SELECT SUM(data_length + index_length) / 1024 / 1024 "
                 "FROM information_schema.tables WHERE table_schema = DATABASE()")
        ).first()
        return float(row[0] or 0)
    except Exception:
        return 0.0


def _get_latest_backup() -> BackupInfo | None:
    """读 BACKUP_DIR 下最新的 studio_*.sql.gz"""
    try:
        files = sorted(
            glob.glob(os.path.join(BACKUP_DIR, "studio_*.sql.gz")),
            key=os.path.getmtime,
            reverse=True,
        )
        if not files:
            return None
        p = files[0]
        st = os.stat(p)
        return BackupInfo(
            filename=os.path.basename(p),
            size_kb=st.st_size / 1024,
            mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        )
    except Exception:
        return None


@router.get("", response_model=StatsResponse)
def get_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    now = datetime.utcnow()
    yesterday = now - timedelta(hours=24)

    return StatsResponse(
        users_total=db.query(User).count(),
        users_active=db.query(User).filter(User.is_active.is_(True)).count(),
        releases_total=db.query(ClientRelease).count(),
        releases_active=db.query(ClientRelease).filter(ClientRelease.is_active.is_(True)).count(),
        sessions_active=db.query(SessionModel).filter(SessionModel.revoked_at.is_(None)).count(),
        recent_audit_count=db.query(AuditLog).filter(AuditLog.created_at >= yesterday).count(),
        db_size_mb=_get_db_size_mb(db),
        latest_backup=_get_latest_backup(),
    )
