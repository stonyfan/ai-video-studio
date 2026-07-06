"""健康检查"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db


router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)):
    """服务+数据库探活"""
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"ok": True, "db": db_ok}
