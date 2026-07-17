"""
往真实后端插一条 client_release 记录 + 启动本地 installer 服务

步骤：
  1. 启动 http server 服务一个假 installer.bin（端口 18080）
  2. 登录 admin 拿 access_token
  3. POST /api/v1/admin/releases 创建 release 记录
  4. 验证 /api/v1/updates/check 返回 has_update=true

用法：
  python scripts/seed_release.py
  python scripts/seed_release.py --version 0.6.0 --admin-pass yourpass

前置：
  - docker compose up（backend on :8000）
  - .env 里的 ADMIN_PASSWORD 可用（默认 change-me-admin）

脚本会一直运行（保持 installer 服务），按 Ctrl+C 停止。
"""
import argparse
import hashlib
import http.server
import json
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request

BACKEND = "http://localhost:8000/api/v1"
INSTALLER_PORT = 18080

# 假安装包：固定 100KB 字节（sha256 跨运行一致）
INSTALLER_BODY = bytes(range(256)) * 400
INSTALLER_SHA256 = hashlib.sha256(INSTALLER_BODY).hexdigest()


class InstallerHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # 静音

    def do_GET(self):
        if self.path == "/installer.bin":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(INSTALLER_BODY)))
            self.end_headers()
            self.wfile.write(INSTALLER_BODY)
        else:
            self.send_response(404)
            self.end_headers()


def start_installer_server():
    srv = socketserver.TCPServer(("127.0.0.1", INSTALLER_PORT), InstallerHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


def api_request(method: str, path: str, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{BACKEND}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {"raw": e.read().decode(errors="replace")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="0.5.0")
    ap.add_argument("--min-supported", default="0.4.0")
    ap.add_argument("--notes", default="测试版本：验证客户端自动更新链路")
    ap.add_argument("--admin-user", default="admin")
    ap.add_argument("--admin-pass", default="change-me-admin")
    args = ap.parse_args()

    print("=" * 60)
    print("Seed client release + 启动 installer 服务")
    print("=" * 60)

    # 1. 启动 installer server
    print(f"\n[1/4] 启动 installer 服务 http://localhost:{INSTALLER_PORT}/installer.bin")
    srv = start_installer_server()
    time.sleep(0.4)
    download_url = f"http://localhost:{INSTALLER_PORT}/installer.bin"
    print(f"      download_url = {download_url}")
    print(f"      sha256       = {INSTALLER_SHA256}")

    # 2. 登录
    print(f"\n[2/4] 登录 admin ({args.admin_user})")
    status, data = api_request("POST", "/auth/login", {
        "username": args.admin_user,
        "password": args.admin_pass,
        "device_fp": "seed-script",
    })
    if status != 200:
        print(f"      ❌ 登录失败: HTTP {status}")
        print(f"         响应: {data}")
        print(f"      💡 如果改过 ADMIN_PASSWORD，用 --admin-pass xxx")
        srv.shutdown()
        sys.exit(1)
    token = data["access_token"]
    print(f"      ✅ 拿到 access_token")

    # 3. 创建 release
    print(f"\n[3/4] POST /api/v1/admin/releases (version={args.version})")
    status, data = api_request("POST", "/admin/releases", {
        "version": args.version,
        "download_url": download_url,
        "sha256": INSTALLER_SHA256,
        "min_supported": args.min_supported,
        "release_notes": args.notes,
        "is_active": True,
    }, token=token)
    if status == 409:
        print(f"      ⚠️  版本已存在（继续验证）")
    elif status != 201:
        print(f"      ❌ 创建失败: HTTP {status}")
        print(f"         响应: {data}")
        srv.shutdown()
        sys.exit(1)
    else:
        print(f"      ✅ 创建成功：id={data.get('id')}")

    # 4. 验证 check 接口
    print(f"\n[4/4] 验证 GET /api/v1/updates/check?current_version=0.4.0")
    status, info = api_request("GET", "/updates/check?current_version=0.4.0&platform=windows")
    print(f"      has_update        = {info.get('has_update')}")
    print(f"      latest_version    = {info.get('latest_version')}")
    print(f"      download_url      = {info.get('download_url')}")
    print(f"      current_deprecated = {info.get('current_deprecated')}")

    if not info.get("has_update"):
        print("\n❌ check 没返回 has_update=true，检查 release 记录的 is_active 字段")
        srv.shutdown()
        sys.exit(1)

    print("\n" + "=" * 60)
    print("✅ 后端就绪，现在去启动 Electron：")
    print("=" * 60)
    print()
    print("  cd D:/ai-video-studio/desktop")
    print("  # 可选：缩短首检延迟（默认 30s → 3s）")
    print("  # PowerShell:")
    print("  $env:UPDATE_CHECK_DELAY_MS=3000; npm run dev")
    print("  # 或 cmd:")
    print("  set UPDATE_CHECK_DELAY_MS=3000 && npm run dev")
    print()
    print("启动后会看到：")
    print("  - 启动后 N 秒（N=UPDATE_CHECK_DELAY_MS，默认 30000）")
    print("    右下角弹'发现新版本 v0.5.0'通知")
    print("  - 点'立即下载' → 下载进度 → '已就绪'")
    print("  - 点'立即安装并重启' → Electron 退出")
    print("    （installer 是 100KB 字节数据不是真 exe，会启动失败，但说明链路通了）")
    print()
    print("也可登录后去 Settings → 点'检查更新'手动触发")
    print()
    print("--- installer 服务保持运行中，按 Ctrl+C 停止 ---")
    print("=" * 60)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[stop] 关闭 installer 服务")
        srv.shutdown()


if __name__ == "__main__":
    main()
