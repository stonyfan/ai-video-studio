"""FastAPI 入口"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine, SessionLocal
from .models import User, ClientRelease  # noqa: F401  ensure models registered
from .security import hash_password
from .api import auth, users_admin, updates, health


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表 + 创建初始 admin"""
    # 从 database 模块动态拿 engine（测试时可能被 reinit）
    from . import database
    Base.metadata.create_all(bind=database.engine)
    _ensure_admin()
    yield


def _ensure_admin():
    """首次启动自动建 admin 账号"""
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
        if not existing:
            admin = User(
                username=settings.ADMIN_USERNAME,
                password_hash=hash_password(settings.ADMIN_PASSWORD),
                role="admin",
                license_expires_at=None,  # 永久
                is_active=True,
            )
            db.add(admin)
            db.commit()
            print(f"[init] 已创建 admin 账号: {settings.ADMIN_USERNAME}")
    finally:
        db.close()


app = FastAPI(
    title="AI Video Studio API",
    version="0.1.0",
    description="账号/授权/客户端更新控制服务",
    lifespan=lifespan,
)

# CORS（开发期全开，生产收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.ENV == "development" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 路由
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users_admin.router, prefix="/api/v1/admin/users", tags=["admin/users"])
app.include_router(updates.router, prefix="/api/v1/updates", tags=["updates"])
app.include_router(updates.admin_router, prefix="/api/v1/admin/releases", tags=["admin/releases"])
