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


def test_update_check_rollout_percentage(client):
    """灰度比例：pct=0 永不命中，pct=100 必命中"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # v0.4.0 灰度 0%（不命中任何设备）
    r = client.post("/api/v1/admin/releases", json={
        "version": "0.4.0",
        "download_url": "https://example.com/v0.4.0.zip",
        "sha256": "b" * 64,
        "min_supported": "0.1.0",
        "rollout_percentage": 0,
    }, headers=h)
    assert r.status_code == 201

    # 即使 v0.3.0 在灰度 100%，最新版应该是 v0.4.0（按 id desc 扫描）
    # 但 v0.4.0 pct=0，应跳过 → 命中 v0.3.0
    # 先加 v0.3.0
    client.post("/api/v1/admin/releases", json={
        "version": "0.3.0",
        "download_url": "https://example.com/v0.3.0.zip",
        "sha256": "a" * 64,
        "min_supported": "0.1.0",
    }, headers=h)

    # 设备检查：v0.4.0 pct=0 跳过，v0.3.0 pct=100 命中
    r = client.get("/api/v1/updates/check?current_version=0.2.0",
                   headers={"X-Device-FP": "device-A"})
    data = r.json()
    assert data["has_update"] is True
    assert data["latest_version"] == "0.3.0", "v0.4.0 灰度 0 应被跳过"


def test_update_check_force_upgrade(client):
    """force_upgrade：即使有更高版本，也强制升级到 target"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # v0.5.0 + force_upgrade
    client.post("/api/v1/admin/releases", json={
        "version": "0.5.0",
        "download_url": "https://example.com/v0.5.0.zip",
        "sha256": "c" * 64,
        "min_supported": "0.1.0",
        "force_upgrade": True,
    }, headers=h)

    # v0.6.0 普通（更高版本，无 force）
    client.post("/api/v1/admin/releases", json={
        "version": "0.6.0",
        "download_url": "https://example.com/v0.6.0.zip",
        "sha256": "d" * 64,
        "min_supported": "0.1.0",
    }, headers=h)

    # 客户端 v0.4.0 检查：应指向 v0.5.0 + current_deprecated=True + force_upgrade=True
    r = client.get("/api/v1/updates/check?current_version=0.4.0",
                   headers={"X-Device-FP": "device-B"})
    data = r.json()
    assert data["has_update"] is True
    assert data["latest_version"] == "0.5.0", "force_upgrade 应指向目标版本，而非更高版本"
    assert data["force_upgrade"] is True
    assert data["current_deprecated"] is True


def test_update_check_device_fp_fallback(client):
    """缺 X-Device-FP header 时应正常返回（用 IP 兜底）"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    client.post("/api/v1/admin/releases", json={
        "version": "0.3.0",
        "download_url": "https://example.com/v0.3.0.zip",
        "sha256": "a" * 64,
        "min_supported": "0.1.0",
        "rollout_percentage": 50,
    }, headers=h)

    # 不带 header — 应正常响应，不应 500
    r = client.get("/api/v1/updates/check?current_version=0.2.0")
    assert r.status_code == 200
    data = r.json()
    assert "has_update" in data


def test_admin_release_lifecycle(client):
    """admin 创建 + 改灰度 + force_upgrade + 回滚"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 创建 v0.7.0 默认字段
    r = client.post("/api/v1/admin/releases", json={
        "version": "0.7.0",
        "download_url": "https://example.com/v0.7.0.zip",
        "sha256": "f" * 64,
        "min_supported": "0.4.0",
    }, headers=h)
    assert r.status_code == 201
    rid = r.json()["id"]
    assert r.json()["rollout_percentage"] == 100
    assert r.json()["force_upgrade"] is False
    assert r.json()["grace_hours"] == 24

    # 改灰度 30 + force_upgrade
    r = client.patch(f"/api/v1/admin/releases/{rid}", json={
        "rollout_percentage": 30,
        "force_upgrade": True,
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["rollout_percentage"] == 30
    assert r.json()["force_upgrade"] is True
    assert r.json()["rolled_back_at"] is None

    # 调 rollback 端点
    r = client.post(f"/api/v1/admin/releases/{rid}/rollback", headers=h)
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["rolled_back_at"] is not None

    # 再次 rollback 幂等（时间戳不变）
    first_rolled_back = r.json()["rolled_back_at"]
    r = client.post(f"/api/v1/admin/releases/{rid}/rollback", headers=h)
    assert r.json()["rolled_back_at"] == first_rolled_back


def test_admin_patch_is_active_false_marks_rolled_back(client):
    """PATCH is_active: True → False 自动填 rolled_back_at"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.post("/api/v1/admin/releases", json={
        "version": "0.8.0",
        "download_url": "https://example.com/v0.8.0.zip",
        "sha256": "0" * 64,
        "min_supported": "0.4.0",
    }, headers=h)
    rid = r.json()["id"]
    assert r.json()["rolled_back_at"] is None

    r = client.patch(f"/api/v1/admin/releases/{rid}", json={"is_active": False}, headers=h)
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    assert r.json()["rolled_back_at"] is not None, "is_active True→False 应自动填 rolled_back_at"


# === Phase 11: 下载量 / 升级成功率 ===

def test_release_download_count_increments(client, tmp_path, monkeypatch):
    """GET /releases/Setup X.Y.Z.exe → 对应 release.download_count +1"""
    # mock RELEASES_DIR 到临时目录
    monkeypatch.setattr("app.main.RELEASES_DIR", tmp_path)

    # 创建 dummy 安装包文件
    (tmp_path / "AI Video Studio Setup 0.9.0.exe").write_bytes(b"dummy installer content")

    # admin 创建 release
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.post("/api/v1/admin/releases", json={
        "version": "0.9.0",
        "download_url": "http://localhost:8000/releases/AI Video Studio Setup 0.9.0.exe",
        "sha256": "e" * 64,
        "min_supported": "0.4.0",
    }, headers=h)

    # GET 安装包 2 次
    r = client.get("/releases/AI Video Studio Setup 0.9.0.exe")
    assert r.status_code == 200
    r = client.get("/releases/AI Video Studio Setup 0.9.0.exe")
    assert r.status_code == 200

    # admin 查列表 → download_count=2
    r = client.get("/api/v1/admin/releases", headers=h)
    rel = next(x for x in r.json() if x["version"] == "0.9.0")
    assert rel["download_count"] == 2, "GET /releases/Setup 2 次 → download_count=2"

    # 其他文件不影响计数
    (tmp_path / "manifest.json").write_text("{}")
    client.get("/releases/manifest.json")
    r = client.get("/api/v1/admin/releases", headers=h)
    rel = next(x for x in r.json() if x["version"] == "0.9.0")
    assert rel["download_count"] == 2, "GET 非匹配文件不应影响计数"

    # path traversal 防护
    r = client.get("/releases/..%2Fetc%2Fpasswd")
    # %2F 会被解码成 / → 命中 path traversal 检查 → 404
    assert r.status_code == 404


def test_report_upgrade_increments_count(client):
    """POST /updates/report-upgrade {to_version} → upgrade_success_count +1"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.post("/api/v1/admin/releases", json={
        "version": "0.9.0",
        "download_url": "http://x/y.exe",
        "sha256": "e" * 64,
        "min_supported": "0.4.0",
    }, headers=h)

    # 上报升级 2 次（counter 不去重）
    r = client.post("/api/v1/updates/report-upgrade",
                    json={"from_version": "0.4.0", "to_version": "0.9.0"},
                    headers={"X-Device-FP": "dev-1"})
    assert r.status_code == 204
    r = client.post("/api/v1/updates/report-upgrade",
                    json={"from_version": "0.4.0", "to_version": "0.9.0"},
                    headers={"X-Device-FP": "dev-2"})
    assert r.status_code == 204

    # admin 查列表 → upgrade_success_count=2
    r = client.get("/api/v1/admin/releases", headers=h)
    rel = next(x for x in r.json() if x["version"] == "0.9.0")
    assert rel["upgrade_success_count"] == 2

    # 不存在的 to_version → 404
    r = client.post("/api/v1/updates/report-upgrade",
                    json={"to_version": "9.9.9"})
    assert r.status_code == 404


def test_release_out_includes_metrics(client):
    """ReleaseOut 默认带 download_count / upgrade_success_count（初始 0）"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.post("/api/v1/admin/releases", json={
        "version": "0.9.0",
        "download_url": "http://x/y.exe",
        "sha256": "e" * 64,
        "min_supported": "0.4.0",
    }, headers=h)
    assert r.status_code == 201
    data = r.json()
    assert data["download_count"] == 0
    assert data["upgrade_success_count"] == 0


# === Phase 7: session_type 隔离 ===

def test_session_type_isolation(client, test_db):
    """同 user 同 type 互踢；跨 type（desktop / web）共存"""
    from app.models import Session as SessionModel

    # 第一次登录（desktop）
    r1 = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
        "session_type": "desktop",
        "device_fp": "device-desktop",
    })
    assert r1.status_code == 200
    token_desktop = r1.json()["access_token"]

    # 第二次登录（web）
    r2 = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
        "session_type": "web",
        "device_fp": "device-web",
    })
    assert r2.status_code == 200
    token_web = r2.json()["access_token"]

    # 两个 token 都还能用（跨 type 共存）
    r_desktop_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_desktop}"})
    r_web_me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_web}"})
    assert r_desktop_me.status_code == 200, "desktop token 应仍有效"
    assert r_web_me.status_code == 200, "web token 应仍有效"

    # 第三次登录（desktop 再登一次 → 应顶掉第一次 desktop，不影响 web）
    r3 = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
        "session_type": "desktop",
        "device_fp": "device-desktop-2",
    })
    assert r3.status_code == 200

    # 第一次的 desktop token 应失效
    r_desktop_old = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_desktop}"})
    assert r_desktop_old.status_code == 401, "同 type 新登应顶掉旧 desktop"

    # web token 仍应有效
    r_web_still = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_web}"})
    assert r_web_still.status_code == 200, "web token 不应受 desktop 重登影响"


def test_session_type_default_is_desktop(client):
    """login 不传 session_type 时默认 desktop"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    assert r.status_code == 200
    # 验证 default：拿 admin sessions 列表看 session_type
    admin_token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {admin_token}"}
    rs = client.get("/api/v1/admin/sessions?active_only=true", headers=h)
    assert rs.status_code == 200
    rows = rs.json()
    assert any(s["session_type"] == "desktop" for s in rows), "默认应为 desktop"


# === Phase 6: sessions / audit / stats ===def test_admin_sessions_list_and_revoke(client, test_db):
    """admin 列 sessions + revoke（用另一个用户的 session，避免误 revoke 自己）"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    admin_token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {admin_token}"}

    # 建一个普通用户 + 让它登录 → 产生一个 session
    client.post("/api/v1/admin/users", json={
        "username": "session_user",
        "password": "pass123456",
    }, headers=h)
    client.post("/api/v1/auth/login", json={
        "username": "session_user",
        "password": "pass123456",
        "device_fp": "session_user_device",
    })

    # 列表（active_only 默认 True），过滤该用户的 session
    r = client.get("/api/v1/admin/sessions?user_id=2", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    sid = data[0]["id"]
    assert data[0]["revoked_at"] is None
    assert data[0]["username"] == "session_user"

    # revoke
    r = client.post(f"/api/v1/admin/sessions/{sid}/revoke", headers=h)
    assert r.status_code == 200
    assert r.json()["revoked_at"] is not None

    # 再次列（active_only=true），刚 revoke 的应消失
    r = client.get("/api/v1/admin/sessions?active_only=true&user_id=2", headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    sid_list = [s["id"] for s in r.json()]
    assert sid not in sid_list

    # active_only=false 应能查到刚 revoke 的
    r = client.get("/api/v1/admin/sessions?active_only=false&user_id=2", headers=h)
    sid_list = [s["id"] for s in r.json()]
    assert sid in sid_list


def test_audit_log_recorded(client, test_db):
    """admin 写操作应自动写 audit_logs"""
    from app.models import AuditLog

    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    admin_token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {admin_token}"}

    # 触发一次 admin 写操作
    client.post("/api/v1/admin/users", json={
        "username": "audit_target_user",
        "password": "pass123456",
    }, headers=h)

    # 查 audit log
    db = test_db()
    logs = db.query(AuditLog).filter(AuditLog.action == "user.create").all()
    db.close()
    assert len(logs) >= 1
    log = logs[-1]
    assert log.actor_username == settings.ADMIN_USERNAME
    assert log.target_type == "user"
    assert "audit_target_user" in (log.target_snapshot or "")


def test_audit_logs_filter(client):
    """audit log 过滤参数生效"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 造一条 release.create
    client.post("/api/v1/admin/releases", json={
        "version": "0.0.1",
        "download_url": "http://x",
        "sha256": "f" * 64,
        "min_supported": "0.0.1",
    }, headers=h)

    # 过滤 action=release.create 应有
    r = client.get("/api/v1/admin/audit-logs?action=release.create", headers=h)
    assert r.status_code == 200
    assert any(log["action"] == "release.create" for log in r.json())

    # 过滤 action=user.create（不应出现 release）
    r = client.get("/api/v1/admin/audit-logs?action=user.update", headers=h)
    assert all(log["action"] == "user.update" for log in r.json())


def test_admin_stats(client):
    """stats 端点返回结构正确"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/api/v1/admin/stats", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert "users_total" in data
    assert "users_active" in data
    assert "releases_total" in data
    assert "releases_active" in data
    assert "sessions_active" in data
    assert "recent_audit_count" in data
    assert data["users_total"] >= 1
    assert data["users_active"] >= 1


# === Phase 7: vision proxy ===

def _seed_provider_key(test_db, provider="qwen-vl", name="test-key"):
    """直插一条 provider_key 到 DB（用 crypto 服务加密）"""
    from app.models import ProviderKey
    from app.services import crypto
    db = test_db()
    k = ProviderKey(
        provider=provider,
        name=name,
        api_key_encrypted=crypto.encrypt("sk-test-fake-key"),
        base_url="https://example.test/v1",
        is_active=True,
    )
    db.add(k)
    db.commit()
    db.refresh(k)
    db.close()
    return k.id


def test_vision_proxy_rejects_unknown_provider(client):
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/vision/not-a-provider/chat/completions",
                    json={"model": "x", "messages": []}, headers=h)
    assert r.status_code == 404


def test_vision_proxy_no_active_key(client):
    """provider 没配 key → 503"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    r = client.post("/api/v1/vision/qwen-vl/chat/completions",
                    json={"model": "qwen-vl-plus", "messages": []}, headers=h)
    assert r.status_code == 503, r.text


def test_vision_proxy_records_usage_and_forwards(client, test_db, monkeypatch):
    """成功透传：mock 上游 → 写 model_usage"""
    import json
    from app.services import provider_router

    key_id = _seed_provider_key(test_db)

    # mock httpx.AsyncClient
    class _FakeResp:
        status_code = 200
        def json(self):
            return {
                "id": "chatcmpl-fake",
                "choices": [{"message": {"content": "hello"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            self.last_url = url
            self.last_headers = headers
            self.last_body = json
            return _FakeResp()

    monkeypatch.setattr("app.api.vision.httpx.AsyncClient", _FakeClient)

    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    r = client.post("/api/v1/vision/qwen-vl/chat/completions",
                    json={"model": "qwen-vl-plus",
                          "messages": [{"role": "user", "content": "hi"}]},
                    headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "hello"

    # model_usage 写了一条
    from app.models import ModelUsage
    db = test_db()
    usage = db.query(ModelUsage).filter(ModelUsage.provider == "qwen-vl").all()
    assert len(usage) == 1
    u = usage[0]
    assert u.status == "success"
    assert u.input_tokens == 10
    assert u.output_tokens == 5
    assert u.estimated_cost_cny > 0
    db.close()


def test_vision_proxy_rate_limited(client, test_db, monkeypatch):
    """连发 N+1 次 → 第 N+1 次 429"""
    from app.services import rate_limit
    rate_limit.reset_for_test()
    _seed_provider_key(test_db)

    # mock 上游（直接成功，不真发请求）
    class _FakeResp:
        status_code = 200
        def json(self): return {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None): return _FakeResp()
    monkeypatch.setattr("app.api.vision.httpx.AsyncClient", _FakeClient)

    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}

    limit = settings.VISION_RATE_LIMIT_PER_MIN
    for i in range(limit):
        r = client.post("/api/v1/vision/qwen-vl/chat/completions",
                        json={"model": "qwen-vl-plus", "messages": []}, headers=h)
        assert r.status_code == 200, f"第 {i+1} 次应通过，实际 {r.status_code}"

    # 第 limit+1 次应 429
    r = client.post("/api/v1/vision/qwen-vl/chat/completions",
                    json={"model": "qwen-vl-plus", "messages": []}, headers=h)
    assert r.status_code == 429, f"超限应 429，实际 {r.status_code}"

    # model_usage 写了一条 rate_limited
    from app.models import ModelUsage
    db = test_db()
    rl_records = db.query(ModelUsage).filter(ModelUsage.status == "rate_limited").all()
    assert len(rl_records) >= 1
    db.close()
    rate_limit.reset_for_test()


# === Phase 7 Step 4: admin provider-keys + model-usage ===

def test_provider_key_crud_and_mask(client, test_db):
    """CRUD：创建返回 masked，不返回明文"""
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}

    # create
    r = client.post("/api/v1/admin/provider-keys", json={
        "provider": "qwen-vl", "name": "Qwen 主号",
        "api_key": "sk-1234567890abcdefghijklmnop",
    }, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "qwen-vl"
    assert body["name"] == "Qwen 主号"
    assert "sk-123" in body["api_key_masked"]   # 前 6 位可见
    assert "mnop" in body["api_key_masked"]       # 后 4 位可见
    assert "4567890abcdefghijkl" not in body["api_key_masked"]   # 中间不暴露
    key_id = body["id"]

    # list
    r = client.get("/api/v1/admin/provider-keys", headers=h)
    assert r.status_code == 200
    assert any(k["id"] == key_id for k in r.json())

    # patch (改名 + 停用)
    r = client.patch(f"/api/v1/admin/provider-keys/{key_id}",
                     json={"name": "Qwen 主号(已停)", "is_active": False}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Qwen 主号(已停)"
    assert r.json()["is_active"] is False

    # delete
    r = client.delete(f"/api/v1/admin/provider-keys/{key_id}", headers=h)
    assert r.status_code == 204
    # 再次 list 应不见
    r = client.get("/api/v1/admin/provider-keys", headers=h)
    assert not any(k["id"] == key_id for k in r.json())


def test_model_usage_summary(client, test_db, monkeypatch):
    """summary 端点能正确聚合"""
    from app.services import rate_limit
    rate_limit.reset_for_test()
    _seed_provider_key(test_db)

    class _FakeResp:
        status_code = 200
        def json(self): return {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None): return _FakeResp()
    monkeypatch.setattr("app.api.vision.httpx.AsyncClient", _FakeClient)

    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    # 调 2 次
    for _ in range(2):
        client.post("/api/v1/vision/qwen-vl/chat/completions",
                    json={"model": "qwen-vl-plus", "messages": []}, headers=h)

    # summary
    r = client.get("/api/v1/admin/model-usage/summary?window=today", headers=h)
    assert r.status_code == 200
    s = r.json()
    assert s["total_requests"] >= 2
    assert s["total_input_tokens"] >= 200
    assert s["total_output_tokens"] >= 100
    assert s["total_cost_cny"] > 0
    assert any(p["provider"] == "qwen-vl" for p in s["by_provider"])

    # list
    r = client.get("/api/v1/admin/model-usage?limit=10", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) >= 2
    assert rows[0]["username"] == settings.ADMIN_USERNAME
    rate_limit.reset_for_test()


# ===== 错误上报 (Phase 8) =====

def test_error_report_upload_and_admin_list_download(client, test_db, monkeypatch):
    """用户上传错误报告 → admin 列表/下载/改状态"""
    import os
    import tempfile
    from app.config import settings as app_settings

    # 用临时目录做 ERROR_REPORTS_DIR
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(app_settings, "ERROR_REPORTS_DIR", tmpdir)

        # admin 登录
        r = client.post("/api/v1/auth/login", json={
            "username": settings.ADMIN_USERNAME,
            "password": settings.ADMIN_PASSWORD,
        })
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        # 上传一个 zip（用 bytes 模拟）
        zip_bytes = b"PK\x03\x04" + b"\x00" * 100
        r = client.post(
            "/api/v1/error-reports",
            headers=h,
            files={"file": ("report.zip", zip_bytes, "application/zip")},
            data={
                "message": "导出视频时崩溃",
                "job_id": "job_abc123",
                "client_version": "0.8.1",
                "client_platform": "win32",
            },
        )
        assert r.status_code == 201, r.text
        rid = r.json()["id"]
        assert r.json()["ok"] is True

        # 文件已落盘
        files = os.listdir(tmpdir)
        assert len(files) == 1
        assert files[0].startswith("err_u1_")

        # admin 列表
        r = client.get("/api/v1/admin/error-reports", headers=h)
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == rid
        assert row["username"] == settings.ADMIN_USERNAME
        assert row["job_id"] == "job_abc123"
        assert row["message"] == "导出视频时崩溃"
        assert row["client_version"] == "0.8.1"
        assert row["status"] == "open"
        assert row["file_size"] == len(zip_bytes)

        # 下载
        r = client.get(f"/api/v1/admin/error-reports/{rid}/download", headers=h)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"
        assert r.content == zip_bytes

        # 改状态
        r = client.patch(f"/api/v1/admin/error-reports/{rid}", headers=h,
                         json={"status": "resolved", "admin_note": "已修复于 0.8.2"})
        assert r.status_code == 200
        row = r.json()
        assert row["status"] == "resolved"
        assert row["admin_note"] == "已修复于 0.8.2"

        # 过滤 status=open 应为空
        r = client.get("/api/v1/admin/error-reports?status=open", headers=h)
        assert r.status_code == 200
        assert len(r.json()) == 0


def test_error_report_rejects_oversize(client, test_db, monkeypatch):
    """超过 ERROR_REPORT_MAX_BYTES 上限应 413"""
    import tempfile
    from app.config import settings as app_settings

    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setattr(app_settings, "ERROR_REPORTS_DIR", tmpdir)
        # 把上限设小（10 字节）
        monkeypatch.setattr(app_settings, "ERROR_REPORT_MAX_BYTES", 10)

        r = client.post("/api/v1/auth/login", json={
            "username": settings.ADMIN_USERNAME,
            "password": settings.ADMIN_PASSWORD,
        })
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}

        big = b"\x00" * 1024  # 1KB > 10B
        r = client.post(
            "/api/v1/error-reports",
            headers=h,
            files={"file": ("big.zip", big, "application/zip")},
            data={"message": "x"},
        )
        assert r.status_code == 413
        # 不应写表
        r = client.get("/api/v1/admin/error-reports", headers=h)
        assert len(r.json()) == 0


def test_error_report_requires_auth(client):
    """未登录上传应 401"""
    r = client.post(
        "/api/v1/error-reports",
        files={"file": ("r.zip", b"x", "application/zip")},
        data={"message": "x"},
    )
    assert r.status_code == 401


# ===== Prompt 集版本管理 (Phase 10) =====

VALID_YAML = """\
templates:
  triplet_detect:
    default: |
      {vertical_prompt}
      hello prompt v1
  scene_analyze:
    default: |
      scene
verticals:
  default: "x"
"""

VALID_YAML_V2 = """\
templates:
  triplet_detect:
    default: |
      {vertical_prompt}
      hello prompt v2 (modified)
  scene_analyze:
    default: |
      scene
verticals:
  default: "x"
"""

INVALID_YAML_NO_TRIPLET = """\
templates:
  scene_analyze:
    default: |
      scene
verticals:
  default: "x"
"""

INVALID_YAML_BAD_SYNTAX = "templates: [unclosed"


def _seed_default_prompt_set(test_db, content: str = VALID_YAML) -> int:
    """测试用：手动建一个默认 prompt 集（SQLite 跳过 alembic，要手动 seed）"""
    from app.models import PromptSet
    db = test_db()
    ps = PromptSet(
        name="默认",
        description="测试默认集",
        content_yaml=content,
        version=1,
        is_default=True,
        is_active=True,
    )
    db.add(ps)
    db.commit()
    db.refresh(ps)
    pid = ps.id
    db.close()
    return pid


def _admin_login(client) -> dict:
    r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_user(client, h: dict, username: str) -> int:
    r = client.post("/api/v1/admin/users", json={
        "username": username,
        "password": "test123456",
    }, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_prompt_set_default_seeded_via_helper(client, test_db):
    """默认集通过 helper 创建后，list 应返回 1 条 is_default"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    r = client.get("/api/v1/admin/prompt-sets", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["is_default"] is True
    assert rows[0]["name"] == "默认"
    assert rows[0]["version"] == 1


def test_user_gets_default_when_unbound(client, test_db):
    """未绑定 prompt 集的用户 → GET /prompts/me 返回默认集"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    uid = _create_user(client, h, "user1")

    # user 登录
    r = client.post("/api/v1/auth/login", json={
        "username": "user1", "password": "test123456",
    })
    uh = {"Authorization": f"Bearer {r.json()['access_token']}"}

    r = client.get("/api/v1/prompts/me", headers=uh)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "默认"
    assert "templates" in data["content_yaml"]
    assert data["version"] == 1
    # Cache-Control 头存在
    assert "cache-control" in {k.lower() for k in r.headers.keys()}

    # /me/version 轻量端点
    r = client.get("/api/v1/prompts/me/version", headers=uh)
    assert r.status_code == 200
    assert r.json()["version"] == 1


def test_user_gets_assigned_set(client, test_db):
    """绑定 prompt 集 → 返回绑定的集"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    uid = _create_user(client, h, "user1")

    # 创建一个新集
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "客户A",
        "description": "客户A 专属",
        "content_yaml": VALID_YAML_V2,
    }, headers=h)
    assert r.status_code == 201, r.text
    new_id = r.json()["id"]

    # 给 user1 绑定
    r = client.patch(f"/api/v1/admin/users/{uid}", json={
        "prompt_set_id": new_id,
    }, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["prompt_set_id"] == new_id

    # user1 拉到的应该是客户A 集
    r = client.post("/api/v1/auth/login", json={
        "username": "user1", "password": "test123456",
    })
    uh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    r = client.get("/api/v1/prompts/me", headers=uh)
    assert r.status_code == 200
    assert r.json()["id"] == new_id
    assert "v2 (modified)" in r.json()["content_yaml"]


def test_prompt_set_crud_and_version_bump(client, test_db):
    """CRUD + content_yaml 变更 → version+1"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)

    # create
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "客户A",
        "description": "测试",
        "content_yaml": VALID_YAML,
    }, headers=h)
    assert r.status_code == 201
    ps_id = r.json()["id"]
    assert r.json()["version"] == 1

    # update name only → version 不变
    r = client.patch(f"/api/v1/admin/prompt-sets/{ps_id}", json={
        "name": "客户A v2",
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "客户A v2"
    assert r.json()["version"] == 1  # name 变更不 bump

    # update content_yaml → version+1
    r = client.patch(f"/api/v1/admin/prompt-sets/{ps_id}", json={
        "content_yaml": VALID_YAML_V2,
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["version"] == 2

    # get
    r = client.get(f"/api/v1/admin/prompt-sets/{ps_id}", headers=h)
    assert r.status_code == 200
    assert r.json()["version"] == 2
    assert "v2 (modified)" in r.json()["content_yaml"]


def test_prompt_set_yaml_validation(client, test_db):
    """非法 YAML → 422"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)

    # 缺 triplet_detect
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "x",
        "content_yaml": INVALID_YAML_NO_TRIPLET,
    }, headers=h)
    assert r.status_code == 422

    # 语法错误
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "y",
        "content_yaml": INVALID_YAML_BAD_SYNTAX,
    }, headers=h)
    assert r.status_code == 422


def test_prompt_set_optimistic_lock_409(client, test_db):
    """expected_version 不匹配 → 409"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "x", "content_yaml": VALID_YAML,
    }, headers=h)
    ps_id = r.json()["id"]

    # 传 expected_version=99（实际是 1）→ 409
    r = client.patch(f"/api/v1/admin/prompt-sets/{ps_id}", json={
        "name": "new",
        "expected_version": 99,
    }, headers=h)
    assert r.status_code == 409


def test_prompt_set_cannot_delete_default(client, test_db):
    """删除默认集 → 400"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    # 默认集 id=1（seeded）
    r = client.delete("/api/v1/admin/prompt-sets/1", headers=h)
    assert r.status_code == 400


def test_prompt_set_cannot_delete_bound_user(client, test_db):
    """删除有绑定用户的集 → 400"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    uid = _create_user(client, h, "user_bound")

    # 建新集 + 绑定用户
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "x", "content_yaml": VALID_YAML,
    }, headers=h)
    new_id = r.json()["id"]
    client.patch(f"/api/v1/admin/users/{uid}", json={
        "prompt_set_id": new_id,
    }, headers=h)

    # 删除应失败
    r = client.delete(f"/api/v1/admin/prompt-sets/{new_id}", headers=h)
    assert r.status_code == 400
    assert "1" in r.json()["detail"]  # "仍有 1 个用户绑定"


def test_prompt_set_soft_delete(client, test_db):
    """删除普通集 → 软删（deleted_at 非空），list 默认不显示"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "x", "content_yaml": VALID_YAML,
    }, headers=h)
    new_id = r.json()["id"]

    r = client.delete(f"/api/v1/admin/prompt-sets/{new_id}", headers=h)
    assert r.status_code == 204

    # list 默认不显示
    r = client.get("/api/v1/admin/prompt-sets", headers=h)
    rows = r.json()
    assert all(r["id"] != new_id for r in rows)

    # include_deleted=True 显示
    r = client.get("/api/v1/admin/prompt-sets?include_deleted=true", headers=h)
    rows = r.json()
    assert any(r["id"] == new_id for r in rows)


def test_prompt_set_duplicate(client, test_db):
    """复制 → 新集 name 带「(副本)」、is_default=False、version 重置为 1"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "客户A",
        "content_yaml": VALID_YAML_V2,
    }, headers=h)
    src_id = r.json()["id"]

    # 先把 content_yaml 改了让 version=2
    client.patch(f"/api/v1/admin/prompt-sets/{src_id}", json={
        "content_yaml": VALID_YAML,
    }, headers=h)

    r = client.post(f"/api/v1/admin/prompt-sets/{src_id}/duplicate", headers=h)
    assert r.status_code == 201
    new = r.json()
    assert new["name"] == "客户A(副本)"
    assert new["is_default"] is False
    assert new["version"] == 1  # 重置
    assert new["id"] != src_id


def test_user_assign_prompt_set_via_patch(client, test_db):
    """PATCH user 显式 null → 解绑走默认"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    uid = _create_user(client, h, "user_patch")

    # 建新集
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "x", "content_yaml": VALID_YAML,
    }, headers=h)
    new_id = r.json()["id"]

    # 绑定
    r = client.patch(f"/api/v1/admin/users/{uid}", json={
        "prompt_set_id": new_id,
    }, headers=h)
    assert r.json()["prompt_set_id"] == new_id

    # 解绑（显式 null）
    r = client.patch(f"/api/v1/admin/users/{uid}", json={
        "prompt_set_id": None,
    }, headers=h)
    assert r.status_code == 200
    assert r.json()["prompt_set_id"] is None

    # 不传字段 → 不改（仍 None）
    r = client.patch(f"/api/v1/admin/users/{uid}", json={
        "display_name": "Test",
    }, headers=h)
    assert r.json()["prompt_set_id"] is None
    assert r.json()["display_name"] == "Test"


def test_user_assign_nonexistent_set_404(client, test_db):
    """绑定不存在的 prompt_set_id → 404"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)
    uid = _create_user(client, h, "user_404")

    r = client.patch(f"/api/v1/admin/users/{uid}", json={
        "prompt_set_id": 99999,
    }, headers=h)
    assert r.status_code == 404


def test_prompt_set_audit_logged(client, test_db):
    """admin 创建 prompt_set → audit_logs 表有 prompt_set.create 记录"""
    from app.models import AuditLog
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)

    client.post("/api/v1/admin/prompt-sets", json={
        "name": "x", "content_yaml": VALID_YAML,
    }, headers=h)

    db = test_db()
    logs = db.query(AuditLog).filter(AuditLog.action == "prompt_set.create").all()
    assert len(logs) == 1
    assert "name" in (logs[0].target_snapshot or "")
    db.close()


def test_prompt_set_is_default_switch(client, test_db):
    """新集设 is_default=True → 原默认集降级"""
    _seed_default_prompt_set(test_db)
    h = _admin_login(client)

    # 建新集（非默认）
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "新默认", "content_yaml": VALID_YAML,
        "is_default": False,
    }, headers=h)
    new_id = r.json()["id"]

    # PATCH 切换为默认
    r = client.patch(f"/api/v1/admin/prompt-sets/{new_id}", json={
        "is_default": True,
    }, headers=h)
    assert r.status_code == 200

    # 验证：新集 is_default=True，原集 is_default=False
    r = client.get("/api/v1/admin/prompt-sets", headers=h)
    rows = {r["id"]: r for r in r.json()}
    assert rows[new_id]["is_default"] is True
    assert rows[1]["is_default"] is False


# === Phase 12: 用户可选 prompt 集 ===

def _create_user_and_login(client, test_db, username="test_user", password="pass123456"):
    """helper：建普通用户 + 返回 (user_obj, token)"""
    admin_r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME,
        "password": settings.ADMIN_PASSWORD,
    })
    admin_h = {"Authorization": f"Bearer {admin_r.json()['access_token']}"}
    r = client.post("/api/v1/admin/users", json={
        "username": username,
        "password": password,
    }, headers=admin_h)
    assert r.status_code == 201
    user_data = r.json()
    # 登录拿 token
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return user_data, r.json()["access_token"]


def test_user_options_includes_default_for_new_user(client, test_db):
    """新用户（无 options 表记录）→ GET /me/options 至少返回 is_default 集"""
    _seed_default_prompt_set(test_db)
    user_data, token = _create_user_and_login(client, test_db, "user_options_new")
    h = {"Authorization": f"Bearer {token}"}

    r = client.get("/api/v1/prompts/me/options", headers=h)
    assert r.status_code == 200
    options = r.json()
    assert len(options) >= 1
    # 应该有 is_default=True 的那一条
    assert any(o["is_default"] for o in options), "options 至少包含 is_default 集"
    # is_current 应该指向 is_default（新用户没选过）
    current = [o for o in options if o["is_current"]]
    assert len(current) == 1
    assert current[0]["is_default"] is True


def test_user_options_includes_currently_selected(client, test_db):
    """用户当前 prompt_set_id 即使不在 options 表里，也应在列表中出现"""
    _seed_default_prompt_set(test_db)
    admin_r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD,
    })
    admin_h = {"Authorization": f"Bearer {admin_r.json()['access_token']}"}

    # 建 1 个非默认 prompt 集
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "集A", "content_yaml": "templates:\n  triplet_detect:\n    default: test",
    }, headers=admin_h)
    set_a_id = r.json()["id"]

    # 建用户 + admin 设 prompt_set_id = 集 A（不分配 options）
    user_data, token = _create_user_and_login(client, test_db, "user_options_cur")
    user_id = user_data["id"]
    client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_id": set_a_id,
    }, headers=admin_h)

    h = {"Authorization": f"Bearer {token}"}
    r = client.get("/api/v1/prompts/me/options", headers=h)
    options = r.json()
    option_ids = {o["id"] for o in options}
    assert set_a_id in option_ids, "用户当前 prompt_set_id 必须出现在 options 列表"
    assert any(o["is_default"] for o in options), "默认集也应包含在 options 里"


def test_user_select_validates_in_options(client, test_db):
    """select 校验：在 options 内 → 成功；不在 → 403；不存在 → 404"""
    _seed_default_prompt_set(test_db)
    admin_r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD,
    })
    admin_h = {"Authorization": f"Bearer {admin_r.json()['access_token']}"}

    # 建 3 个非默认 prompt 集
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "可选A", "content_yaml": "templates:\n  triplet_detect:\n    default: test",
    }, headers=admin_h)
    set_a_id = r.json()["id"]
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "可选B", "content_yaml": "templates:\n  triplet_detect:\n    default: test",
    }, headers=admin_h)
    set_b_id = r.json()["id"]
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "未授权C", "content_yaml": "templates:\n  triplet_detect:\n    default: test",
    }, headers=admin_h)
    set_c_id = r.json()["id"]

    # 建用户 + admin 分配 options=[A, B]
    user_data, token = _create_user_and_login(client, test_db, "user_select")
    user_id = user_data["id"]
    client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_option_ids": [set_a_id, set_b_id],
    }, headers=admin_h)

    h = {"Authorization": f"Bearer {token}"}

    # select A → 成功
    r = client.post("/api/v1/prompts/me/select",
                    json={"prompt_set_id": set_a_id}, headers=h)
    assert r.status_code == 200, f"select A 应成功: {r.text}"
    assert r.json()["id"] == set_a_id

    # select C（未分配）→ 403
    r = client.post("/api/v1/prompts/me/select",
                    json={"prompt_set_id": set_c_id}, headers=h)
    assert r.status_code == 403, f"select 未授权集应 403: {r.text}"

    # select 9999（不存在）→ 404
    r = client.post("/api/v1/prompts/me/select",
                    json={"prompt_set_id": 9999}, headers=h)
    assert r.status_code == 404


def test_admin_assign_multiple_options_via_patch(client, test_db):
    """PATCH prompt_set_option_ids=[1,2,3] → options 表有 3 条；再 PATCH [1,3] → 剩 2 条"""
    _seed_default_prompt_set(test_db)
    admin_r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD,
    })
    admin_h = {"Authorization": f"Bearer {admin_r.json()['access_token']}"}

    # 建 3 个 prompt 集（不用默认集避免干扰）
    ids = []
    for name in ["集1", "集2", "集3"]:
        r = client.post("/api/v1/admin/prompt-sets", json={
            "name": name, "content_yaml": "templates:\n  triplet_detect:\n    default: test",
        }, headers=admin_h)
        ids.append(r.json()["id"])

    # 建用户
    user_data, _ = _create_user_and_login(client, test_db, "user_assign")
    user_id = user_data["id"]

    # PATCH [所有 3 个]
    r = client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_option_ids": ids,
    }, headers=admin_h)
    assert r.status_code == 200
    assert sorted(r.json()["prompt_set_option_ids"]) == sorted(ids)

    # PATCH [集1, 集3]（移除集2）
    r = client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_option_ids": [ids[0], ids[2]],
    }, headers=admin_h)
    assert r.status_code == 200
    remaining = r.json()["prompt_set_option_ids"]
    assert ids[1] not in remaining, "集2 应被移除"
    assert ids[0] in remaining and ids[2] in remaining

    # PATCH []（清空）
    r = client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_option_ids": [],
    }, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["prompt_set_option_ids"] == []


def test_admin_remove_current_set_falls_back(client, test_db):
    """用户当前 prompt_set_id 被从 options 移除时 → 自动 fallback 到 is_default 集"""
    _seed_default_prompt_set(test_db)
    admin_r = client.post("/api/v1/auth/login", json={
        "username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD,
    })
    admin_h = {"Authorization": f"Bearer {admin_r.json()['access_token']}"}

    # 建 1 个非默认集
    r = client.post("/api/v1/admin/prompt-sets", json={
        "name": "可移除集", "content_yaml": "templates:\n  triplet_detect:\n    default: test",
    }, headers=admin_h)
    custom_id = r.json()["id"]

    # 找 is_default 集 id
    r = client.get("/api/v1/admin/prompt-sets", headers=admin_h)
    default_id = next(x["id"] for x in r.json() if x["is_default"])

    # 建用户 + 设当前 prompt_set_id = custom + 分配 options=[custom]
    user_data, _ = _create_user_and_login(client, test_db, "user_fallback")
    user_id = user_data["id"]
    client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_id": custom_id,
        "prompt_set_option_ids": [custom_id],
    }, headers=admin_h)

    # 确认初始状态
    r = client.get("/api/v1/admin/users", headers=admin_h)
    user = next(u for u in r.json() if u["id"] == user_id)
    assert user["prompt_set_id"] == custom_id

    # 清空 options → 用户当前被移除 → fallback 到 is_default
    r = client.patch(f"/api/v1/admin/users/{user_id}", json={
        "prompt_set_option_ids": [],
    }, headers=admin_h)
    assert r.status_code == 200
    assert r.json()["prompt_set_id"] == default_id, "清空 options 后应 fallback 到 is_default"
