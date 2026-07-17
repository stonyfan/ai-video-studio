"""Provider key 加密/解密（Fernet）。

key 从 settings.JWT_SECRET 派生（PBKDF2-HMAC-SHA256）。

注意：换 JWT_SECRET 会导致所有现有 provider_key 无法解密 — 换前需重新录入。
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import settings


_SALT = b"phase7-provider-keys-v1"
_PBKDF2_ROUNDS = 100_000


def _derive_key() -> bytes:
    raw = hashlib.pbkdf2_hmac(
        "sha256",
        settings.JWT_SECRET.encode("utf-8"),
        _SALT,
        _PBKDF2_ROUNDS,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw)


_fernet = Fernet(_derive_key())


def encrypt(plain: str) -> str:
    """明文 → Fernet ciphertext (str)"""
    return _fernet.encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Fernet ciphertext → 明文；失败抛 ValueError"""
    try:
        return _fernet.decrypt(token.encode("utf-8")).decode("utf-8")
    except (InvalidToken, Exception) as e:
        raise ValueError(f"decrypt 失败（key 可能已损坏或 JWT_SECRET 已变）: {e}") from e


def mask(plain: str, visible_prefix: int = 6, visible_suffix: int = 4) -> str:
    """生成展示用的 mask：sk-abc…wxyz"""
    if len(plain) <= visible_prefix + visible_suffix:
        return "*" * len(plain)
    return f"{plain[:visible_prefix]}…{plain[-visible_suffix:]}"
