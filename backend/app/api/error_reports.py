"""用户端错误上报端点（不带 /admin 前缀，普通用户也能调）"""
import os
import shutil
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, ErrorReport
from ..config import settings
from ..deps import get_current_user


router = APIRouter()


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def upload_error_report(
    message: str = Form(..., min_length=1, max_length=2000),
    job_id: str | None = Form(None),
    client_version: str | None = Form(None),
    client_platform: str | None = Form(None),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """用户上报错误：multipart 上传一个 zip 包，后端落盘 + 写表"""
    # 大小检查（读 chunks 累计，避免一次性读进内存）
    reported_size = 0
    total = 0
    tmp_path = os.path.join(settings.ERROR_REPORTS_DIR, f".tmp_{uuid.uuid4().hex}")
    os.makedirs(settings.ERROR_REPORTS_DIR, exist_ok=True)
    try:
        with open(tmp_path, "wb") as f:
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > settings.ERROR_REPORT_MAX_BYTES:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"上传文件超过 {settings.ERROR_REPORT_MAX_BYTES // 1024 // 1024}MB 限制",
                    )
                f.write(chunk)
        reported_size = total
    except HTTPException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"保存失败: {e}")

    # 重命名为正式文件名：{id前缀}_{user_id}_{timestamp}.zip
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = f"err_u{user.id}_{ts}_{uuid.uuid4().hex[:6]}.zip"
    final_path = os.path.join(settings.ERROR_REPORTS_DIR, safe_name)
    try:
        shutil.move(tmp_path, final_path)
    except Exception as e:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"重命名失败: {e}")

    # 写表
    report = ErrorReport(
        user_id=user.id,
        job_id=job_id,
        message=message,
        file_path=safe_name,
        file_size=reported_size,
        client_version=client_version,
        client_platform=client_platform,
        status="open",
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    return {"id": report.id, "ok": True}
