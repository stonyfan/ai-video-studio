"""修复 release 6 的 release_notes 编码"""
import json
import urllib.request

BASE = "http://localhost:8000/api/v1"


def main():
    # login
    req = urllib.request.Request(
        f"{BASE}/auth/login",
        data=json.dumps({"username": "admin", "password": "change-me-admin"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        tok = json.loads(resp.read())["access_token"]

    notes = (
        "Phase 12: 用户端 prompt 集切换\n"
        "- Settings 页新增「Prompt 集」Card\n"
        "- 用户可在 admin 分配的可选池中自由切换\n"
        "- 切换后下次任务生效"
    )
    body = json.dumps({"release_notes": notes}).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}/admin/releases/6",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {tok}",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())
    print("release_notes:", data["release_notes"])


if __name__ == "__main__":
    main()
