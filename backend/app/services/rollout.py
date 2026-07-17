"""灰度发布命中算法。

给定 device_fp + release_id + rollout_percentage，确定该设备是否命中灰度。

关键约束：
- 同 (device_fp, release_id, rollout_percentage) 输入必须始终输出同一结果（幂等）
- 不依赖 PYTHONHASHSEED（用 sha256，不用内置 hash()）
- pct=100 永远命中；pct=0 永不命中
- pct=30 命中集合必须是 pct=60 命中集合的子集（单调性）
"""
from __future__ import annotations

import hashlib


def _bucket(device_fp: str, release_id: int) -> int:
    """对 (device_fp, release_id) 算一个稳定的 0-99 bucket。

    用 sha256 取前 8 hex（32 bit），% 100 得到桶号。
    不加盐 — 同设备同 release 每次必须算出同一值。
    """
    if not device_fp:
        # 空 device_fp 兜底（防止 None 传入崩）
        device_fp = ""
    key = f"{device_fp}:{release_id}".encode("utf-8")
    h = hashlib.sha256(key).hexdigest()
    return int(h[:8], 16) % 100


def is_in_rollout(device_fp: str, release_id: int, pct: int) -> bool:
    """判断设备是否命中此 release 的灰度。

    >>> is_in_rollout("any", 1, 0)
    False
    >>> is_in_rollout("any", 1, 100)
    True
    >>> is_in_rollout("dev1", 1, 30) == is_in_rollout("dev1", 1, 30)
    True
    """
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    return _bucket(device_fp, release_id) < pct
