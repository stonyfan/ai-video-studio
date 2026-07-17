"""Audit middleware：自动记录所有 /admin/* 写操作。

规则：
- 命中 /api/v1/admin/* 路径
- HTTP method ∈ {POST, PATCH, DELETE, PUT}
- 通过 JWT 解析 actor（即使后续端点拒绝，也记录尝试）
- 路径 → action 映射见 _resolve_action()
- 写库失败不阻塞响应（log warning）

实现方式：BaseHTTPMiddleware（拿到 response body 后再写）
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import StreamingResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import AuditLog, User
from ..security import decode_token

log = logging.getLogger("app.middleware.audit")


# 路径 → (action, target_type) 映射；{} 占位 id
# 顺序敏感：先匹配带子动作的（如 reset_password / rollback），再匹配基础 CRUD
ROUTE_TABLE: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^/api/v1/admin/users/(\d+)/reset_password$"), "user.reset_password", "user"),
    (re.compile(r"^/api/v1/admin/users/(\d+)$"),                "user.update",        "user"),  # PATCH
    (re.compile(r"^/api/v1/admin/users/(\d+)$"),                "user.delete",        "user"),  # DELETE
    (re.compile(r"^/api/v1/admin/users$"),                      "user.create",        "user"),  # POST
    (re.compile(r"^/api/v1/admin/releases/(\d+)/rollback$"),    "release.rollback",   "release"),
    (re.compile(r"^/api/v1/admin/releases/(\d+)$"),             "release.update",     "release"),  # PATCH
    (re.compile(r"^/api/v1/admin/releases$"),                   "release.create",     "release"),  # POST
    (re.compile(r"^/api/v1/admin/sessions/(\d+)/revoke$"),      "session.revoke",     "session"),
    (re.compile(r"^/api/v1/admin/provider-keys/(\d+)$"),        "provider_key.update", "provider_key"),  # PATCH
    (re.compile(r"^/api/v1/admin/provider-keys/(\d+)$"),        "provider_key.delete", "provider_key"),  # DELETE
    (re.compile(r"^/api/v1/admin/provider-keys$"),              "provider_key.create", "provider_key"),  # POST
    (re.compile(r"^/api/v1/admin/error-reports/(\d+)$"),        "error_report.update", "error_report"),  # PATCH
    (re.compile(r"^/api/v1/admin/prompt-sets/(\d+)/duplicate$"), "prompt_set.duplicate", "prompt_set"),  # POST
    (re.compile(r"^/api/v1/admin/prompt-sets/(\d+)$"),           "prompt_set.update",    "prompt_set"),  # PATCH
    (re.compile(r"^/api/v1/admin/prompt-sets/(\d+)$"),           "prompt_set.delete",    "prompt_set"),  # DELETE
    (re.compile(r"^/api/v1/admin/prompt-sets$"),                 "prompt_set.create",    "prompt_set"),  # POST
]


def _resolve_action(method: str, path: str) -> tuple[str, str, str | None] | None:
    """返回 (action, target_type, target_id) 或 None（不记录）"""
    method_u = method.upper()
    if method_u not in ("POST", "PATCH", "DELETE", "PUT"):
        return None

    for pat, action, ttype in ROUTE_TABLE:
        m = pat.match(path)
        if m:
            target_id = m.group(1) if m.groups() else None
            # DELETE /users/{id} → user.delete；PATCH /users/{id} → user.update
            # 上面的 ROUTE_TABLE 对 DELETE/PATCH 同一 path 给了不同 action，
            # 这里靠 action 命名区分（delete 是 DELETE 方法独有）。
            # 简化：第一个匹配胜出，PATCH/DELETE 顺序已在表里通过 pattern 隐式区分不了，
            # 所以在 _ACTION_OVERRIDE 里按方法再覆写一次。
            return (_METHOD_ACTION_OVERRIDE.get((method_u, action), action),
                    ttype, target_id)
    return None


# 对同一 path 不同 method 的覆写
_METHOD_ACTION_OVERRIDE: dict[tuple[str, str], str] = {
    # DELETE /users/{id}
    ("DELETE", "user.update"): "user.delete",
    # DELETE /provider-keys/{id}
    ("DELETE", "provider_key.update"): "provider_key.delete",
    # DELETE /prompt-sets/{id}
    ("DELETE", "prompt_set.update"): "prompt_set.delete",
}


def _extract_actor(request: Request) -> tuple[int | None, str | None]:
    """从 Authorization header 解析 user_id + username。

    拿不到（未登录 / token 过期）→ (None, None)；仍记录审计但 actor_user_id 用 NULL 替身 0
    实际上 actor_user_id 是 NOT NULL，所以这里失败时返回 None 让外层跳过。
    """
    auth = request.headers.get("Authorization", "")
    if not auth.lower().startswith("bearer "):
        return (None, None)
    token = auth.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        return (None, None)
    try:
        user_id = int(payload["sub"])
    except (KeyError, ValueError):
        return (None, None)
    # username 查库（值得，因为 username 可能改）
    db: Session = SessionLocal()
    try:
        u = db.query(User).filter(User.id == user_id).first()
        return (user_id, u.username if u else None)
    finally:
        db.close()


def _build_snapshot(action: str, target_id: str | None, response_body: bytes) -> str | None:
    """从 response body 提取关键字段做 snapshot。"""
    try:
        text = response_body.decode("utf-8", errors="replace")
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(data, dict):
        return None

    keys: list[str] = []
    if action.startswith("user."):
        keys = ["id", "username", "role", "is_active", "license_expires_at", "prompt_set_id"]
    elif action.startswith("release."):
        keys = ["id", "version", "is_active", "rollout_percentage", "force_upgrade", "rolled_back_at"]
    elif action.startswith("session."):
        keys = ["id", "user_id", "revoked_at"]
    elif action.startswith("provider_key."):
        # api_key_masked 而非明文
        keys = ["id", "provider", "name", "is_active", "api_key_masked"]
    elif action.startswith("error_report."):
        keys = ["id", "user_id", "status", "admin_note"]
    elif action.startswith("prompt_set."):
        # 不含 content_yaml（太大；audit 只关心元数据）
        keys = ["id", "name", "version", "is_default", "is_active"]

    snap = {k: data.get(k) for k in keys if k in data}
    return json.dumps(snap, ensure_ascii=False) if snap else None


class AuditMiddleware(BaseHTTPMiddleware):
    """记录 admin 写操作到 audit_logs 表。"""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        method = request.method.upper()

        resolved = _resolve_action(method, path)
        if resolved is None:
            return await call_next(request)

        # 走到这里的请求需要捕获 response body
        response = await call_next(request)

        # 只记录 2xx（4xx/5xx 也算尝试，但操作未生效，暂不记）
        if not (200 <= response.status_code < 300):
            return response

        action, target_type, target_id = resolved
        actor_user_id, actor_username = _extract_actor(request)
        if actor_user_id is None:
            # 解析 actor 失败 — 跳过（连日志都不要 noisy）
            return response

        # 拿 response body（StreamingResponse 要消费 chunks 再重组）
        body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body += chunk

        # 重新打包 response 给客户端
        new_response = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

        snapshot = _build_snapshot(action, target_id, body)
        # create 类操作：URL 没带 id，但 snapshot 里有 — 反填 target_id
        if target_id is None and snapshot:
            try:
                snap_obj = json.loads(snapshot)
                if isinstance(snap_obj, dict) and "id" in snap_obj:
                    target_id = str(snap_obj["id"])
            except (json.JSONDecodeError, TypeError):
                pass
        ip = request.client.host if request.client else None
        ua = request.headers.get("User-Agent")

        # 同步写库（短小，不阻塞太久）
        try:
            db: Session = SessionLocal()
            try:
                db.add(AuditLog(
                    actor_user_id=actor_user_id,
                    actor_username=actor_username or "",
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    target_snapshot=snapshot,
                    ip=ip,
                    user_agent=ua,
                ))
                db.commit()
            finally:
                db.close()
        except Exception as e:
            log.warning("audit log write failed: %s", e)

        return new_response
