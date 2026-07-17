"""每用户滑动窗口限速（进程内）。

简单实现：dict[user_id, deque[timestamp]]；每次请求清理过期项再判断长度。
单进程方案；多 worker 部署需换 Redis。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from ..config import settings


_lock = threading.Lock()
_buckets: dict[int, deque[float]] = defaultdict(deque)
_window_sec = 60.0


def check_and_record(user_id: int) -> bool:
    """True=允许通过；False=超限。

    清理 user 桶里 60s 之外的旧时间戳，再判断当前是否超限。
    通过则把当前时间戳 append 进去。
    """
    limit = settings.VISION_RATE_LIMIT_PER_MIN
    now = time.monotonic()
    with _lock:
        bucket = _buckets[user_id]
        cutoff = now - _window_sec
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return False
        bucket.append(now)
        return True


def reset_for_test() -> None:
    """测试用：清空所有 bucket"""
    with _lock:
        _buckets.clear()
