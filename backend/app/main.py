"""FastAPI 入口"""
import logging
import os
import re
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, SessionLocal, get_db
from .models import User, ClientRelease, ProviderKey, ModelUsage, ErrorReport, PromptSet  # noqa: F401  ensure models registered
from .security import hash_password
from .api import auth, users_admin, updates, health
from .api import admin_sessions, admin_audit, admin_stats
from .api import admin_provider_keys, admin_model_usage
from .api import admin_error_reports, error_reports
from .api import admin_prompt_sets, prompts
from .api import vision
from .middleware.audit import AuditMiddleware

log = logging.getLogger("app.main")


def _run_migrations() -> None:
    """生产环境跑 alembic upgrade head；测试环境跳过。

    失败不抛异常，仅 log warning（避免阻塞服务启动）。
    """
    if settings.ENV != "production":
        # 测试/开发：Base.metadata.create_all 由 lifespan 兜底
        return
    try:
        from alembic import command
        from alembic.config import Config
        from pathlib import Path

        cfg_path = Path(__file__).resolve().parent.parent / "alembic.ini"
        if not cfg_path.exists():
            log.warning("alembic.ini not found at %s, skip migrations", cfg_path)
            return
        cfg = Config(str(cfg_path))
        cfg.set_main_option(
            "script_location",
            str(Path(__file__).resolve().parent.parent / "alembic"),
        )
        command.upgrade(cfg, "head")
        log.info("alembic upgrade head completed")
    except Exception as e:
        log.warning("alembic upgrade failed: %s — falling back to create_all", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时跑 migration + 创建初始 admin"""
    from . import database

    _run_migrations()
    # 测试环境兜底（migration 跳过时也要建表）
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

# Audit middleware（记录所有 /api/v1/admin/* 写操作）
app.add_middleware(AuditMiddleware)

# 路由
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users_admin.router, prefix="/api/v1/admin/users", tags=["admin/users"])
app.include_router(updates.router, prefix="/api/v1/updates", tags=["updates"])
app.include_router(updates.admin_router, prefix="/api/v1/admin/releases", tags=["admin/releases"])
app.include_router(admin_sessions.router, prefix="/api/v1/admin/sessions", tags=["admin/sessions"])
app.include_router(admin_audit.router, prefix="/api/v1/admin/audit-logs", tags=["admin/audit"])
app.include_router(admin_stats.router, prefix="/api/v1/admin/stats", tags=["admin/stats"])
app.include_router(admin_provider_keys.router, prefix="/api/v1/admin/provider-keys", tags=["admin/provider-keys"])
app.include_router(admin_model_usage.router, prefix="/api/v1/admin/model-usage", tags=["admin/model-usage"])
app.include_router(admin_error_reports.router, prefix="/api/v1/admin/error-reports", tags=["admin/error-reports"])
app.include_router(error_reports.router, prefix="/api/v1/error-reports", tags=["error-reports"])
app.include_router(admin_prompt_sets.router, prefix="/api/v1/admin/prompt-sets", tags=["admin/prompt-sets"])
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["prompts"])
app.include_router(vision.router, prefix="/api/v1/vision", tags=["vision"])


# === Admin UI（静态文件 + SPA fallback） ===
def _register_admin_ui() -> None:
    """注册 /admin/ 静态服务。

    路径优先级：
    1. /admin/static/*  → admin-ui/dist/static/*  （vite 构建产物）
    2. /admin/*         → admin-ui/dist/*          （其他静态资源，如 favicon）
    3. /admin/(任意 SPA 路由) → admin-ui/dist/index.html  （前端路由兜底）

    admin-ui 目录不存在时不挂载（开发期方便）。
    """
    admin_ui_dir = Path(__file__).resolve().parent.parent / "admin-ui" / "dist"
    if not admin_ui_dir.exists():
        log.warning("admin-ui/dist not found at %s, skip mount", admin_ui_dir)
        return

    index_html = admin_ui_dir / "index.html"

    # 静态资源（vite 打包的 assets/）
    assets_dir = admin_ui_dir / "assets"
    if assets_dir.exists():
        app.mount("/admin/assets", StaticFiles(directory=str(assets_dir)), name="admin-assets")

    # 其他静态文件（favicon.ico, logo.png 等）
    @app.get("/admin/{path:path}")
    async def admin_spa(path: str):
        # 先按文件查；查不到 → 返回 index.html（SPA 路由）
        candidate = admin_ui_dir / path
        if path and candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(index_html))

    # /admin 不带斜杠 → 重定向到 /admin/（SPA 入口）
    @app.get("/admin")
    async def admin_root():
        return FileResponse(str(index_html))


_register_admin_ui()


# === 客户端安装包下载（自定义路由 + 下载计数） ===
# Phase 11：路径优先从 RELEASES_DIR 环境变量读（测试可 override），默认 /releases
RELEASES_DIR = Path(os.environ.get("RELEASES_DIR", "/releases"))

# 文件名匹配：AI Video Studio Setup X.Y.Z.exe（大小写不敏感）
_SETUP_RE = re.compile(
    r"^[Aa][Ii][- ][Vv]ideo[- ][Ss]tudio[- ][Ss]etup[- ](\d+\.\d+\.\d+)\.exe$"
)


def _register_releases_dir() -> None:
    """注册 /releases/{filename} 自定义路由。

    用途：
    - 客户端自动更新从同源拉安装包（避免多开端口）
    - Phase 11：每次下载 Setup X.Y.Z.exe → 反查 release → download_count +1

    路径优先级：
    - RELEASES_DIR 环境变量（测试用）
    - 默认 /releases（docker-compose 挂 desktop/release）

    目录不存在时仍注册路由（请求时返回 404），方便测试 mock。
    """
    if not RELEASES_DIR.exists():
        log.warning("%s not found, /releases/* 路由将返回 404", RELEASES_DIR)

    @app.get("/releases/{filename}")
    async def release_file(filename: str, db: Session = Depends(get_db)):
        # path traversal 防护
        if "/" in filename or "\\" in filename or ".." in filename:
            raise HTTPException(status_code=404)
        file_path = RELEASES_DIR / filename
        if not file_path.is_file():
            raise HTTPException(status_code=404)

        # 匹配 Setup X.Y.Z.exe → +1 download_count
        m = _SETUP_RE.match(filename)
        if m:
            version = m.group(1)
            rel = db.query(ClientRelease).filter(
                ClientRelease.version == version
            ).first()
            if rel:
                rel.download_count = (rel.download_count or 0) + 1
                db.commit()

        return FileResponse(str(file_path))


_register_releases_dir()
