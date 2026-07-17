"""user_admin.py — admin 账号管理 CLI 工具

避免每次手敲 curl 调 admin API。

依赖：仅 Python 标准库（urllib + argparse + json），无需 pip install。

用法示例：
    # 列出账号
    python scripts/user_admin.py list

    # 创建账号（默认授权 30 天）
    python scripts/user_admin.py create alice
    python scripts/user_admin.py create bob --days 365    # 一年
    python scripts/user_admin.py create carol --permanent  # 永久
    python scripts/user_admin.py create dave --role admin  # admin 账号

    # 改密
    python scripts/user_admin.py reset-password alice

    # 禁用 / 启用
    python scripts/user_admin.py disable alice
    python scripts/user_admin.py enable alice

    # 改 license
    python scripts/user_admin.py extend alice --days 30
    python scripts/user_admin.py set-permanent alice

    # 删除（admin 不能删）
    python scripts/user_admin.py delete alice

环境变量：
    STUDIO_BACKEND_URL (默认 http://localhost:8000)
    STUDIO_ADMIN_USER  (默认 admin)
    STUDIO_ADMIN_PASS  (默认读 backend/.env)
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def _load_env() -> tuple[str, str, str]:
    """从环境变量 + backend/.env 推导 backend_url / admin_user / admin_pass"""
    backend_url = os.environ.get("STUDIO_BACKEND_URL", "http://localhost:8000").rstrip("/")

    admin_user = os.environ.get("STUDIO_ADMIN_USER", "admin")

    admin_pass = os.environ.get("STUDIO_ADMIN_PASS")
    if not admin_pass:
        # 尝试读 backend/.env
        env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("ADMIN_PASSWORD="):
                    admin_pass = line.split("=", 1)[1].strip()
                    break
    if not admin_pass:
        admin_pass = ""  # 让 login 失败提示更清晰
    return backend_url, admin_user, admin_pass


def _api(method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, dict | str]:
    backend_url, _, _ = _load_env()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{backend_url}{path}",
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req) as resp:
            text = resp.read().decode("utf-8")
            return resp.status, (json.loads(text) if text else {})
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(text)
        except json.JSONDecodeError:
            return e.code, text


def _login() -> str:
    backend_url, admin_user, admin_pass = _load_env()
    if not admin_pass:
        print("[ERROR] 找不到 admin 密码：请设 STUDIO_ADMIN_PASS 或写 backend/.env", file=sys.stderr)
        sys.exit(2)
    status, data = _api("POST", "/api/v1/auth/login", body={
        "username": admin_user,
        "password": admin_pass,
        "device_fp": "user_admin_cli",
    })
    if status != 200:
        print(f"[ERROR] 登录失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    return data["access_token"]


def _fmt_dt(iso: str | None) -> str:
    if iso is None:
        return "永久"
    try:
        d = dt.datetime.fromisoformat(iso)
        return d.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


def _print_user(u: dict) -> None:
    status = "[ok]" if u["is_active"] else "[XX]"
    role_tag = f"[{u['role']}]"
    license = _fmt_dt(u.get("license_expires_at"))
    print(f"  {u['id']:>4}  {status} {role_tag:<8} {u['username']:<20}  license: {license}")


# === subcommands ===

def cmd_list(args: argparse.Namespace) -> None:
    token = _login()
    status, data = _api("GET", "/api/v1/admin/users?limit=200", token=token)
    if status != 200:
        print(f"[ERROR] list 失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    users = data if isinstance(data, list) else []
    print(f"共 {len(users)} 个账号:")
    for u in users:
        _print_user(u)


def cmd_create(args: argparse.Namespace) -> None:
    token = _login()
    body: dict = {
        "username": args.username,
        "password": args.password or getpass.getpass("新密码: "),
    }
    if args.permanent:
        body["license_expires_at"] = None
    elif args.days is not None:
        expires = dt.datetime.utcnow() + dt.timedelta(days=args.days)
        body["license_expires_at"] = expires.isoformat()
    else:
        # 默认 30 天
        expires = dt.datetime.utcnow() + dt.timedelta(days=30)
        body["license_expires_at"] = expires.isoformat()
    if args.role:
        body["role"] = args.role

    status, data = _api("POST", "/api/v1/admin/users", token=token, body=body)
    if status != 201:
        print(f"[ERROR] 创建失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] 已创建账号:")
    _print_user(data)


def cmd_reset_password(args: argparse.Namespace) -> None:
    token = _login()
    uid = _resolve_user_id(token, args.user)
    new_pwd = args.new_password or getpass.getpass("新密码: ")
    status, data = _api("POST", f"/api/v1/admin/users/{uid}/reset_password",
                        token=token, body={"new_password": new_pwd})
    if status != 200:
        print(f"[ERROR] 改密失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] 已改密: {data['username']}")


def cmd_disable(args: argparse.Namespace) -> None:
    token = _login()
    uid = _resolve_user_id(token, args.username)
    status, data = _api("PATCH", f"/api/v1/admin/users/{uid}",
                        token=token, body={"is_active": False})
    if status != 200:
        print(f"[ERROR] 禁用失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] 已禁用: {data['username']}")


def cmd_enable(args: argparse.Namespace) -> None:
    token = _login()
    uid = _resolve_user_id(token, args.username)
    status, data = _api("PATCH", f"/api/v1/admin/users/{uid}",
                        token=token, body={"is_active": True})
    if status != 200:
        print(f"[ERROR] 启用失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] 已启用: {data['username']}")


def cmd_extend(args: argparse.Namespace) -> None:
    token = _login()
    uid = _resolve_user_id(token, args.username)
    expires = dt.datetime.utcnow() + dt.timedelta(days=args.days)
    status, data = _api("PATCH", f"/api/v1/admin/users/{uid}",
                        token=token, body={"license_expires_at": expires.isoformat()})
    if status != 200:
        print(f"[ERROR] 延长失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] license 延到 {expires.strftime('%Y-%m-%d %H:%M')}: {data['username']}")


def cmd_set_permanent(args: argparse.Namespace) -> None:
    token = _login()
    uid = _resolve_user_id(token, args.username)
    status, data = _api("PATCH", f"/api/v1/admin/users/{uid}",
                        token=token, body={"license_expires_at": None})
    if status != 200:
        print(f"[ERROR] 设置永久失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] license 改为永久: {data['username']}")


def cmd_delete(args: argparse.Namespace) -> None:
    token = _login()
    uid = _resolve_user_id(token, args.username)
    status, data = _api("DELETE", f"/api/v1/admin/users/{uid}", token=token)
    if status == 400:
        print(f"[ERROR] {data}", file=sys.stderr)
        sys.exit(1)
    if status != 204:
        print(f"[ERROR] 删除失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] 已删除: {args.username}")


def _resolve_user_id(token: str, username_or_id: str) -> int:
    """支持 username 或数字 id"""
    if username_or_id.isdigit():
        return int(username_or_id)
    status, data = _api("GET", "/api/v1/admin/users?limit=200", token=token)
    if status != 200:
        print(f"[ERROR] 查找用户失败 ({status}): {data}", file=sys.stderr)
        sys.exit(1)
    for u in data:
        if u["username"] == username_or_id:
            return u["id"]
    print(f"[ERROR] 找不到用户: {username_or_id}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Video Studio 用户管理 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出所有账号").set_defaults(func=cmd_list)

    p_create = sub.add_parser("create", help="创建账号（默认授权 30 天）")
    p_create.add_argument("username")
    p_create.add_argument("--password", help="不传则交互式输入")
    p_create.add_argument("--days", type=int, help="授权 N 天")
    p_create.add_argument("--permanent", action="store_true", help="永久授权")
    p_create.add_argument("--role", choices=["user", "admin"], default="user")
    p_create.set_defaults(func=cmd_create)

    p_reset = sub.add_parser("reset-password", help="改密")
    p_reset.add_argument("user", help="用户名或数字 id")
    p_reset.add_argument("--new-password", dest="new_password", help="不传则交互式输入")
    p_reset.set_defaults(func=cmd_reset_password)

    p_disable = sub.add_parser("disable", help="禁用账号")
    p_disable.add_argument("username")
    p_disable.set_defaults(func=cmd_disable)

    p_enable = sub.add_parser("enable", help="启用账号")
    p_enable.add_argument("username")
    p_enable.set_defaults(func=cmd_enable)

    p_extend = sub.add_parser("extend", help="延长 license")
    p_extend.add_argument("username")
    p_extend.add_argument("--days", type=int, required=True)
    p_extend.set_defaults(func=cmd_extend)

    p_perm = sub.add_parser("set-permanent", help="改为永久 license")
    p_perm.add_argument("username")
    p_perm.set_defaults(func=cmd_set_permanent)

    p_del = sub.add_parser("delete", help="删除账号（admin 不能删）")
    p_del.add_argument("username")
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
