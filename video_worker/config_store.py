"""
用户配置本地存储（API key 等）
位置：%APPDATA%/ai-video-studio/config.json（Windows）
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Optional


def _default_config_path() -> Path:
    """跨平台配置文件路径"""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "ai-video-studio" / "config.json"


class ConfigStore:
    """用户配置（API key + 后端地址 + 登录态）"""

    DEFAULT_KEYS = {
        "qwen-vl": {"api_key": "", "model": "qwen-vl-plus"},
        "doubao": {"api_key": "", "model": "doubao-1.5-vision-pro"},
    }

    def __init__(self, path: Optional[Path] = None):
        self.path = path or _default_config_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.path.exists():
            return {"provider_keys": dict(self.DEFAULT_KEYS),
                    "backend_url": "http://localhost:8000/api/v1",
                    "session_token": None}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"provider_keys": dict(self.DEFAULT_KEYS),
                    "backend_url": "http://localhost:8000/api/v1",
                    "session_token": None}

    def _save(self) -> None:
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ===== API key =====

    def get_provider_key(self, provider: str) -> Optional[str]:
        cfg = self._data.get("provider_keys", {}).get(provider, {})
        return cfg.get("api_key") or None

    def set_provider_key(self, provider: str, api_key: str, model: Optional[str] = None) -> None:
        prov = self._data.setdefault("provider_keys", {}).setdefault(
            provider, {"api_key": "", "model": ""}
        )
        prov["api_key"] = api_key
        if model:
            prov["model"] = model
        self._save()

    def get_provider_model(self, provider: str) -> Optional[str]:
        cfg = self._data.get("provider_keys", {}).get(provider, {})
        return cfg.get("model") or None

    # ===== 后端 =====

    def get_backend_url(self) -> str:
        return self._data.get("backend_url", "http://localhost:8000/api/v1")

    def set_backend_url(self, url: str) -> None:
        self._data["backend_url"] = url
        self._save()

    # ===== 登录态（session token）=====

    def get_session_token(self) -> Optional[str]:
        return self._data.get("session_token")

    def set_session_token(self, token: Optional[str]) -> None:
        self._data["session_token"] = token
        self._save()

    # ===== mode =====

    def get_mode(self) -> str:
        """A 直连 / C 代理"""
        return self._data.get("mode", "direct")

    def set_mode(self, mode: str) -> None:
        if mode not in ("direct", "proxy"):
            raise ValueError(f"未知 mode: {mode}")
        self._data["mode"] = mode
        self._save()
