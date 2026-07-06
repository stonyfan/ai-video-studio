"""SQLAlchemy engine + SessionLocal"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import settings


def _make_engine(url: str):
    """根据 URL 创建 engine（mysql 走连接池，sqlite 走简单配置）"""
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,  # 内存 SQLite 共享同一连接
        )
    return create_engine(
        url,
        pool_pre_ping=True,        # 自动重连
        pool_recycle=3600,
        pool_size=10,
        max_overflow=20,
        echo=(settings.ENV == "development"),
    )


engine = _make_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def reinit_engine(new_url: str):
    """重新初始化 engine（测试用）"""
    global engine
    try:
        engine.dispose()
    except Exception:
        pass
    engine = _make_engine(new_url)
    SessionLocal.configure(bind=engine)
    return engine


def get_db():
    """FastAPI 依赖：每个请求拿一个 session，结束自动关"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
