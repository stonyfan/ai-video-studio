"""
Electron 端更新链路 mock server

监听 8000（匹配客户端 backend_url 默认值 http://localhost:8000/api/v1）

端点：
  GET  /api/v1/updates/check    → 模拟后端检查接口
  GET  /installer.bin           → 假安装包（实际是 100KB 字节数据，扩展名 .exe 但不会执行）
  POST /api/v1/auth/login       → 模拟登录（任意账号密码通过）
  POST /api/v1/auth/heartbeat   → 模拟心跳（永远 200）
  POST /api/v1/auth/logout      → 模拟登出

场景控制（命令行 --scenario）：
  normal     - has_update=true, current_deprecated=false（普通更新）
  latest     - has_update=false（已是最新，不会弹通知）
  deprecated - current_deprecated=true（强制更新，弹不可关闭 Modal）
  corrupt    - 下载内容 sha256 不匹配（验证客户端能拦截篡改）

用法：
  python scripts/mock_update_server.py
  python scripts/mock_update_server.py --scenario deprecated
"""
import argparse
import hashlib
import http.server
import json
import socketserver
import sys
from urllib.parse import urlparse, parse_qs


LATEST_VERSION = "0.5.0"
MIN_SUPPORTED = "0.4.0"
RELEASE_NOTES = "测试版本：修复旋转 bug，新增自动更新链路"

# 假安装包：固定 100KB 字节（保证 sha256 跨运行一致）
INSTALLER_BODY = bytes(range(256)) * 400  # 102400 bytes
INSTALLER_SHA256 = hashlib.sha256(INSTALLER_BODY).hexdigest()

# corrupt 场景用的"坏"包：改最后 1 字节
INSTALLER_BAD_BODY = INSTALLER_BODY[:-1] + bytes([(INSTALLER_BODY[-1] + 1) % 256])


def parse_version(v: str):
    return tuple(int(x) for x in v.split("."))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 简化的访问日志，便于看客户端命中了哪些端点
        sys.stdout.write(f"  [server] {self.address_string()} {self.command} {self.path}\n")
        sys.stdout.flush()

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == "/api/v1/updates/check":
            self.handle_check(u)
        elif u.path == "/installer.bin":
            self.handle_installer(corrupt=False)
        elif u.path == "/installer-corrupt.bin":
            self.handle_installer(corrupt=True)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

    def do_POST(self):
        u = urlparse(self.path)
        # 读取 body（即使不解析也要消费掉）
        length = int(self.headers.get("Content-Length", "0") or "0")
        _body = self.rfile.read(length) if length > 0 else b""

        if u.path == "/api/v1/auth/login":
            self.respond_json(200, {
                "access_token": "mock-access-token",
                "refresh_token": "mock-refresh-token",
                "expires_in": 3600,
                "user": {
                    "id": "mock-user",
                    "username": "tester",
                    "role": "admin",
                    "license_expires_at": "2027-01-01",
                }
            })
        elif u.path in ("/api/v1/auth/heartbeat", "/api/v1/auth/logout"):
            self.respond_json(200, {"ok": True})
        elif u.path == "/api/v1/auth/refresh":
            self.respond_json(200, {"access_token": "mock-access-token", "expires_in": 3600})
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"not found")

    def respond_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_check(self, u: urlparse):
        q = parse_qs(u.query)
        cur = q.get("current_version", ["0.0.0"])[0]
        scenario = self.server.scenario  # type: ignore[attr-defined]

        if scenario == "latest":
            has_update = False
        else:
            has_update = parse_version(LATEST_VERSION) > parse_version(cur)

        deprecated = (scenario == "deprecated"
                      and parse_version(cur) < parse_version(MIN_SUPPORTED))

        # corrupt 场景：check 返回正确 sha256，但 download_url 指向被篡改的包
        # 客户端下载后用期望 sha256 校验，会失败 → 拦截
        if scenario == "corrupt":
            download_url = "http://localhost:8000/installer-corrupt.bin"
        else:
            download_url = "http://localhost:8000/installer.bin"
        sha = INSTALLER_SHA256

        body = json.dumps({
            "has_update": has_update,
            "latest_version": LATEST_VERSION if has_update else None,
            "download_url": download_url if has_update else None,
            "sha256": sha if has_update else None,
            "release_notes": RELEASE_NOTES if has_update else None,
            "min_supported": MIN_SUPPORTED,
            "current_deprecated": deprecated,
        }).encode()

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_installer(self, corrupt: bool):
        body = INSTALLER_BAD_BODY if corrupt else INSTALLER_BODY
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ThreadingServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="normal",
                        choices=["normal", "latest", "deprecated", "corrupt"])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print("=" * 60)
    print(f"Mock update server  (scenario={args.scenario})")
    print("=" * 60)
    print(f"  监听:        http://localhost:{args.port}")
    print(f"  check URL:   /api/v1/updates/check?current_version=0.4.0&platform=windows")
    print(f"  installer:   /installer.bin  ({len(INSTALLER_BODY)} bytes)")
    print(f"  sha256:      {INSTALLER_SHA256[:32]}...")
    print()
    print("操作流程:")
    print("  1. 启动 Electron dev:  cd desktop && npm run dev")
    print("  2. 登录任意账号（mock 不响应 auth，需要 bypass）")
    print("     或等 30 秒自动触发（UpdateNotifier 全局监听，无需登录）")
    print("  3. 出现右下角通知 → 点击下载")
    print("  4. 下载完成 → 点击立即安装（Electron 会退出）")
    print()
    print("按 Ctrl+C 停止")
    print("=" * 60)

    server = ThreadingServer(("127.0.0.1", args.port), Handler)
    server.scenario = args.scenario  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] 已停止")
        server.shutdown()


if __name__ == "__main__":
    main()
