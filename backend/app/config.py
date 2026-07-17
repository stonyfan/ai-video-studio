"""配置加载（环境变量）"""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 数据库
    DATABASE_URL: str = "mysql+pymysql://studio:studio@localhost:3306/studio"

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60         # 1 小时
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30           # 30 天
    SESSION_HEARTBEAT_TIMEOUT_MIN: int = 5        # 心跳超时自动失效

    # 初始 admin
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "change-me-in-production"

    # 服务
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENV: str = "development"  # development | production

    # Vision model proxy（Phase 7）
    VISION_RATE_LIMIT_PER_MIN: int = 20   # 每用户每分钟最大请求数
    VISION_UPSTREAM_TIMEOUT_SEC: int = 60  # 调上游 provider 的超时
    VISION_PROXY_ENABLED: bool = True     # 总开关；false 时返回 503

    # 错误报告（Phase 8）
    ERROR_REPORTS_DIR: str = "/data/error_reports"  # 存 zip 的目录
    ERROR_REPORT_MAX_BYTES: int = 20 * 1024 * 1024  # 单文件上限 20MB
    ERROR_REPORT_RETENTION_DAYS: int = 30           # 自动清理超期报告

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",        # 忽略 docker-compose 透传过来的 DB_PASSWORD 等
    )


settings = Settings()
