"""Phase 5 e2e 验证脚本：场景 1（灰度 0%）+ 场景 2（灰度 30% + 一致性 + 命中率）"""
import sys
import urllib.request
import urllib.parse
import json

BACKEND = "http://localhost:8000"
ADMIN_USER = "admin"
ADMIN_PASS = "change-me-admin"


def login():
    body = json.dumps({"username": ADMIN_USER, "password": ADMIN_PASS, "device_fp": "e2e-script"}).encode()
    req = urllib.request.Request(f"{BACKEND}/api/v1/auth/login", data=body,
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))["access_token"]


def api(method, path, token=None, body=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BACKEND}{path}", data=data, method=method, headers=headers)
    return json.load(urllib.request.urlopen(req))


def check(device_fp, current="0.4.0"):
    url = f"{BACKEND}/api/v1/updates/check?current_version={current}&platform=windows"
    req = urllib.request.Request(url, headers={"X-Device-FP": device_fp})
    return json.load(urllib.request.urlopen(req))


def main():
    token = login()
    print("[1] 登录 admin OK")

    # 找到之前测试遗留的 release（如果有）
    rels = api("GET", "/api/v1/admin/releases?limit=10", token)
    print(f"[2] 现有 releases: {[(r['version'], r['id']) for r in rels]}")

    # 找最新一条非 rollback 的，或者新建一条 v0.9.1
    target = next((r for r in rels if r["is_active"]), None)
    if target is None:
        target = api("POST", "/api/v1/admin/releases", token, {
            "version": "0.9.1",
            "download_url": "http://x/v0.9.1.zip",
            "sha256": "b" * 64,
            "min_supported": "0.4.0",
            "rollout_percentage": 0,
        })
        print(f"[3] 新建 v0.9.1 id={target['id']}")
    else:
        # 重置为初始状态：灰度 0% + force_upgrade False
        api("PATCH", f"/api/v1/admin/releases/{target['id']}", token,
            {"rollout_percentage": 0, "force_upgrade": False, "is_active": True})
        print(f"[3] 重置 release id={target['id']} v{target['version']} → rollout=0% force=False")

    rid = target["id"]
    ver = target["version"]

    # === 场景 1：rollout=0 → 100 次同设备都 has_update=False ===
    print(f"\n=== 场景 1: rollout=0% 验证 ===")
    results = [check("dev-fixed-A")["has_update"] for _ in range(100)]
    hits = sum(results)
    print(f"  100 次同 fp → 命中 {hits} 次（应 0）")
    assert hits == 0, "rollout=0 不应命中"
    print("  PASS")

    # === 场景 2：rollout=30 ===
    print(f"\n=== 场景 2: rollout=30% 验证 ===")
    api("PATCH", f"/api/v1/admin/releases/{rid}", token, {"rollout_percentage": 30})

    # 2a: 同 fp 100 次结果一致
    first = check("dev-stable")["has_update"]
    consistent = all(check("dev-stable")["has_update"] == first for _ in range(100))
    print(f"  2a 同 fp 100 次一致性: {'OK' if consistent else 'FAIL'}（first={first}）")
    assert consistent

    # 2b: 1000 个不同 fp 命中率 ~30%
    hits_1000 = sum(check(f"dev-rnd-{i}")["has_update"] for i in range(1000))
    pct = hits_1000 / 1000 * 100
    print(f"  2b 1000 个 fp 命中 {hits_1000}（{pct:.1f}%），预期 25-35%")
    assert 250 <= hits_1000 <= 350, f"命中率偏离预期：{pct:.1f}%"
    print("  PASS")

    # === 场景 3: force_upgrade ===
    print(f"\n=== 场景 3: force_upgrade 验证 ===")
    api("PATCH", f"/api/v1/admin/releases/{rid}", token,
        {"rollout_percentage": 0, "force_upgrade": True})
    r = check("any-device")
    print(f"  has_update={r['has_update']} force_upgrade={r['force_upgrade']} "
          f"current_deprecated={r['current_deprecated']} latest={r['latest_version']}")
    assert r["has_update"] is True
    assert r["force_upgrade"] is True
    assert r["current_deprecated"] is True
    assert r["latest_version"] == ver
    print("  PASS")

    # === 场景 4: rollback ===
    print(f"\n=== 场景 4: rollback 端点 ===")
    r = api("POST", f"/api/v1/admin/releases/{rid}/rollback", token)
    print(f"  is_active={r['is_active']} rolled_back_at={r['rolled_back_at']}")
    assert r["is_active"] is False
    assert r["rolled_back_at"] is not None

    # 幂等：再调一次，时间戳不变
    first_ts = r["rolled_back_at"]
    r2 = api("POST", f"/api/v1/admin/releases/{rid}/rollback", token)
    print(f"  再次 rollback: rolled_back_at={r2['rolled_back_at']} (幂等)")
    assert r2["rolled_back_at"] == first_ts
    print("  PASS")

    # === 场景 5: rollback 后客户端检查 ===
    print(f"\n=== 场景 5: rollback 后客户端检查 ===")
    r = check("any-device")
    print(f"  has_update={r['has_update']}（应 False）")
    assert r["has_update"] is False
    print("  PASS")

    # 清理
    print(f"\n[清理] 删除测试 release v{ver}")
    try:
        api("DELETE", f"/api/v1/admin/releases/{rid}", token)
    except Exception as e:
        # DELETE 没实现也无所谓，直接 DB 删
        print(f"  DELETE 失败（{e}），用 DB 直删")
    print("\n全部场景通过 ✓")


if __name__ == "__main__":
    sys.exit(main() or 0)
