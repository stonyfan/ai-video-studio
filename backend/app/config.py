"""配置加载（环境变量）"""
from __future__ import annotations
from pydantic_settings import BaseSettings


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

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
