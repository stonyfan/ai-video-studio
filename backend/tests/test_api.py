"""端到端 API 测试（SQLite 内存）"""
import sys
from pathlib import Path

# 加 backend 目录到 sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.config import settings
from app.models import User, ClientRelease, Session as SessionModel
import app.models  # 触发模型注册


# ===== fixtures =====

@pytest.fixture(scope="function")
def test_db():
    """每个测试用内存 SQLite（重设全局 engine + 建初始 admin）"""
    from app.database import reinit_engine
    from app.security import hash_password
    engine = reinit_engine("sqlite://")
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # 手动建 admin（避免依赖 lifespan）
    db = TestSession()
    if not db.query(User).filter(User.username == settings.ADMIN_USERNAME).first():
        db.add(User(
            username=settings.ADMIN_USERNAME,
            password_hash=hash_password(settings.ADMIN_PASSWORD),
            role="admin",
            license_expires_at=None,
            is_active=True,
        ))
        db.commit()
    db.close()

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    from app.main import app
    app.dependency_overrides[get_db] = override_get_db

    yield TestSession

    Base.metadata.drop_all(engine)
    app.dependency_overrides.clear()


@pytest.fixture
def client(test_db):
    from app.main import app
    # TestClient 不用 with 避免 lifespan 重复建 admin
    # test_db 已经建好 admin
    yield TestClient(app)


# ===== 测试 =====

def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True


def test_admin_auto_created(test_db):
    """首次启动自动建 admin"""
    from app.models import User
    db = test_db()
    admin = db.query(User).filter(User.username == settings.ADMIN_USERNAME).first()
    assert admin is not None
    assert admin.role == "admin"
    db.close()


def test_login_logout(client):
    # 登录
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
        "device_fp": "test-device",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert "access_token" in data
    assert "refresh_token" in data
    token = data["access_token"]

    # me
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["username"] == settings.ADMIN_USERNAME

    # heartbeat
    r = client.post("/api/v1/auth/heartbeat", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    # logout
    r = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200

    # logout 后 me 应 401
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_login_wrong_password(client):
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": "wrong",
        "device_fp": "x",
    })
    assert r.status_code == 401


def test_single_session_kick(client):
    """单点顶替：第二次登录顶掉第一次"""
    r1 = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
        "device_fp": "device1",
    })
    token1 = r1.json()["access_token"]

    r2 = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
        "device_fp": "device2",
    })
    token2 = r2.json()["access_token"]

    # token1 心跳应失败
    r = client.post("/api/v1/auth/heartbeat", headers={"Authorization": f"Bearer {token1}"})
    assert r.status_code == 401

    # token2 心跳应成功
    r = client.post("/api/v1/auth/heartbeat", headers={"Authorization": f"Bearer {token2}"})
    assert r.status_code == 200


def test_admin_create_user(client):
    """admin 创建用户 + 用户登录"""
    # admin 登录
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    admin_token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {admin_token}"}

    # 创建用户
    r = client.post("/api/v1/admin/users", json={
        "username": "user1",
        "password": "test123456",
    }, headers=h)
    assert r.status_code == 201, r.text

    # 用户登录
    r = client.post("/api/v1/auth/login", json={
        "username": "user1",
        "password": "test123456",
    })
    assert r.status_code == 200

    # 普通用户不能访问 admin 端点
    user_token = r.json()["access_token"]
    r = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {user_token}"})
    assert r.status_code == 403


def test_expired_license_blocked(client, test_db):
    """过期 license 拒绝登录"""
    from datetime import datetime, timedelta, timezone
    from app.models import User
    from app.security import hash_password

    TestSession = test_db
    db = TestSession()
    db.add(User(
        username="expired_user",
        password_hash=hash_password("test123456"),
        license_expires_at=datetime.utcnow() - timedelta(days=1),  # 昨天过期
    ))
    db.commit()
    db.close()

    r = client.post("/api/v1/auth/login", json={
        "username": "expired_user",
        "password": "test123456",
    })
    assert r.status_code == 403


def test_update_check(client):
    """客户端版本检查"""
    # admin 创建一个 release
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    admin_token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {admin_token}"}

    r = client.post("/api/v1/admin/releases", json={
        "version": "0.3.0",
        "download_url": "https://example.com/v0.3.0.zip",
        "sha256": "a" * 64,
        "min_supported": "0.1.0",
        "release_notes": "首个商品化版本",
    }, headers=h)
    assert r.status_code == 201

    # 客户端检查更新
    r = client.get("/api/v1/updates/check?current_version=0.2.0")
    assert r.status_code == 200
    data = r.json()
    assert data["has_update"] is True
    assert data["latest_version"] == "0.3.0"

    # 已是最新
    r = client.get("/api/v1/updates/check?current_version=0.3.0")
    assert r.json()["has_update"] is False
