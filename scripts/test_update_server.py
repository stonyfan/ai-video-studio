"""
更新链路 mock server + 客户端测试

模拟后端：
- GET /api/v1/updates/check → 返回 has_update=true
- GET /installer.bin → 返回假的安装包（实际是任意字节数据）

模拟客户端：
- 调 check → 看响应
- 下载 installer
- sha256 校验
- 报告状态变化
"""
import hashlib
import http.server
import json
import socketserver
import sys
import threading
import time
import urllib.request
from pathlib import Path


# === 准备：生成假安装包（10KB 随机字节） ===
INSTALLER_BODY = bytes(range(256)) * 40  # 10KB 固定字节
INSTALLER_SHA256 = hashlib.sha256(INSTALLER_BODY).hexdigest()
INSTALLER_SIZE = len(INSTALLER_BODY)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静音日志

    def do_GET(self):
        if self.path.startswith("/api/v1/updates/check"):
            # 解析 current_version
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(self.path).query)
            cur = q.get("current_version", ["0.0.0"])[0]

            # 算版本比较：0.4.0 < 0.5.0 → has_update
            def parse(v): return tuple(int(x) for x in v.split("."))
            has_update = parse("0.5.0") > parse(cur)

            body = json.dumps({
                "has_update": has_update,
                "latest_version": "0.5.0" if has_update else None,
                "download_url": "http://localhost:18080/installer.bin",
                "sha256": INSTALLER_SHA256,
                "release_notes": "测试版本：修复旋转 bug，新增自动更新",
                "min_supported": "0.4.0",
                "current_deprecated": parse(cur) < parse("0.4.0"),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/installer.bin":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(INSTALLER_SIZE))
            self.end_headers()
            self.wfile.write(INSTALLER_BODY)

        elif self.path == "/installer-corrupt.bin":
            # 故意返回不同内容，验证 sha256 能拦
            bad = INSTALLER_BODY[:-1] + bytes([(INSTALLER_BODY[-1] + 1) % 256])
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(bad)))
            self.end_headers()
            self.wfile.write(bad)

        else:
            self.send_response(404)
            self.end_headers()


def start_server(port=18080):
    server = socketserver.TCPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def client_check(current_version: str) -> dict:
    """模拟 updater.check()"""
    url = f"http://localhost:18080/api/v1/updates/check?current_version={current_version}&platform=windows"
    print(f"  [client] GET {url}")
    with urllib.request.urlopen(url, timeout=5) as r:
        info = json.loads(r.read())
    return info


def client_download(url: str, dest: Path, expected_sha256: str) -> tuple[bool, str]:
    """模拟 updater.download() + sha256 校验"""
    print(f"  [client] 下载 {url} → {dest.name}")
    with urllib.request.urlopen(url, timeout=10) as r:
        data = r.read()
    actual = hashlib.sha256(data).hexdigest()
    if actual.lower() != expected_sha256.lower():
        dest.unlink(missing_ok=True)
        return False, f"sha256 不匹配：期望 {expected_sha256[:16]}…，实际 {actual[:16]}…"
    dest.write_bytes(data)
    return True, f"sha256 校验通过 ({actual[:16]}…)"


def run_scenario(name: str, current_version: str, expect_fail=False, corrupt_url=None):
    print(f"\n=== 场景：{name} ===")
    info = client_check(current_version)
    print(f"  [client] 响应：has_update={info['has_update']}, "
          f"latest={info['latest_version']}, current_deprecated={info['current_deprecated']}")

    if not info["has_update"]:
        print(f"  [client] 状态：idle（无更新）")
        return

    # 状态：available
    print(f"  [client] 状态：{'available' if not info['current_deprecated'] else 'deprecated (强制更新)'}")

    # 下载
    url = corrupt_url or info["download_url"]
    dest = Path(f"C:/Users/86150/AppData/Local/Temp/mock-setup-{info['latest_version']}.bin")
    ok, msg = client_download(url, dest, info["sha256"])

    if ok:
        print(f"  [client] 状态：downloaded → {msg}")
        print(f"  [client] 文件大小：{dest.stat().st_size} bytes")
        if expect_fail:
            print(f"  [client] ❌ 期望失败但成功了")
        else:
            print(f"  [client] ✅ 通知'立即安装并重启'（跳过实际 install）")
    else:
        print(f"  [client] 状态：failed → {msg}")
        if expect_fail:
            print(f"  [client] ✅ 期望失败，已正确拦截")
        else:
            print(f"  [client] ❌ 意外失败")


def main():
    print("=" * 60)
    print("更新链路验证")
    print("=" * 60)
    print(f"假安装包：{INSTALLER_SIZE} bytes, sha256={INSTALLER_SHA256[:32]}...")

    server = start_server()
    print(f"mock server: http://localhost:18080")

    time.sleep(0.3)

    # 场景 1：当前版本旧，有新版本
    run_scenario("普通更新（0.4.0 → 0.5.0）", "0.4.0")

    # 场景 2：当前版本最新
    run_scenario("已是最新（0.5.0）", "0.5.0")

    # 场景 3：当前版本 < min_supported（强制更新）
    run_scenario("强制更新（0.3.0 < min_supported 0.4.0）", "0.3.0")

    # 场景 4：sha256 不匹配（中间人篡改 / 下载损坏）
    run_scenario("下载内容被篡改（sha256 拦截）", "0.4.0",
                 expect_fail=True, corrupt_url="http://localhost:18080/installer-corrupt.bin")

    server.shutdown()
    print("\n" + "=" * 60)
    print("验证完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
