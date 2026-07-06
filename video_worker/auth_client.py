"""
客户端登录态 + 心跳
- 登录/退出/refresh
- 后台 60s 心跳
- session 失效回调
"""
from __future__ import annotations
import hashlib
import logging
import platform
import threading
import time
import uuid
from typing import Callable, Optional

import requests

from .config_store import ConfigStore


class AuthError(Exception):
    pass


def get_device_fp() -> str:
    """生成设备指纹（host + username hash）"""
    raw = f"{platform.node()}-{platform.uname().system}-{platform.uname().machine}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class AuthClient:
    """登录态管理"""

    HEARTBEAT_INTERVAL_SEC = 60

    def __init__(self, store: Optional[ConfigStore] = None,
                 logger: Optional[logging.Logger] = None):
        self.store = store or ConfigStore()
        self.logger = logger or logging.getLogger(__name__)
        self._token: Optional[str] = self.store.get_session_token()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._session_invalid = False
        self._on_invalid: Optional[Callable[[str], None]] = None

    @property
    def token(self) -> Optional[str]:
        return self._token

    @property
    def is_logged_in(self) -> bool:
        return self._token is not None and not self._session_invalid

    def set_on_invalid_callback(self, cb: Callable[[str], None]) -> None:
        """session 失效时回调（让上层停止任务）"""
        self._on_invalid = cb

    # ===== HTTP 调用 =====

    def _url(self, path: str) -> str:
        base = self.store.get_backend_url().rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    def login(self, username: str, password: str) -> dict:
        """登录"""
        r = requests.post(self._url("/auth/login"), json={
            "username": username,
            "password": password,
            "device_fp": get_device_fp(),
            "user_agent": f"video-worker/{platform.system()}",
        }, timeout=15)
        if r.status_code == 401:
            raise AuthError("用户名或密码错误")
        if r.status_code == 403:
            raise AuthError(r.json().get("detail", "授权失效或账号禁用"))
        r.raise_for_status()
        data = r.json()
        self._token = data["access_token"]
        self.store.set_session_token(self._token)
        self._session_invalid = False
        self._start_heartbeat()
        self.logger.info(f"登录成功 user={data['user'].get('username')}")
        return data

    def logout(self) -> None:
        """退出"""
        if not self._token:
            return
        try:
            requests.post(self._url("/auth/logout"), headers=self._headers(), timeout=10)
        except Exception:
            pass
        self._token = None
        self._session_invalid = True
        self.store.set_session_token(None)
        self.logger.info("已退出登录")

    def heartbeat_once(self) -> bool:
        """单次心跳"""
        if not self._token:
            return False
        try:
            r = requests.post(self._url("/auth/heartbeat"),
                              headers=self._headers(), timeout=10)
            if r.status_code == 200:
                return True
            if r.status_code in (401, 403):
                self._handle_invalid(r.json().get("detail", "session 失效"))
                return False
        except Exception as e:
            self.logger.warning(f"心跳失败（网络）: {e}")
            return True  # 网络问题不算 session 失效
        return False

    def _handle_invalid(self, reason: str) -> None:
        self._session_invalid = True
        self._token = None
        self.store.set_session_token(None)
        self.logger.warning(f"session 失效: {reason}")
        if self._on_invalid:
            try:
                self._on_invalid(reason)
            except Exception:
                pass

    def _start_heartbeat(self) -> None:
        """启动后台心跳线程"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return

        def loop():
            while self._token and not self._session_invalid:
                time.sleep(self.HEARTBEAT_INTERVAL_SEC)
                if not self.heartbeat_once():
                    return

        t = threading.Thread(target=loop, daemon=True, name="auth-heartbeat")
        t.start()
        self._heartbeat_thread = t

    def ensure_session_valid(self) -> None:
        """worker 启动前调用：验证 session 还有效"""
        if not self._token:
            raise AuthError("未登录，请先用 `python -m video_worker --login` 登录")
        if self._session_invalid:
            raise AuthError("session 已失效，请重新登录")
        # 启动心跳（如果还没启）
        if not (self._heartbeat_thread and self._heartbeat_thread.is_alive()):
            # 同步探一次
            if not self.heartbeat_once():
                raise AuthError("session 校验失败")
