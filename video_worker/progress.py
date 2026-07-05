"""
进度上报：内存字典 + 文件双写
- report(job_id, status, error=None)：上报
- get_status(job_id)：查询
"""
from __future__ import annotations
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from .validators import JobStatus
from .storage import get_job_dir

_state: dict[str, dict] = {}
_lock = threading.Lock()
_work_root: Optional[Path] = None


def configure_work_root(work_root: Path) -> None:
    global _work_root
    _work_root = Path(work_root)


def report(job_id: str, status: JobStatus | str,
           error: Optional[dict] = None, work_root: Optional[Path] = None) -> None:
    """上报状态：内存 + progress.json"""
    if isinstance(status, str):
        status = JobStatus(status)
    ts = datetime.now().isoformat(timespec="seconds")
    with _lock:
        prev = _state.get(job_id, {})
        prev.update({
            "job_id": job_id,
            "status": status.value,
            "timestamp": ts,
        })
        if error:
            prev["error"] = error
        # 状态时间戳历史
        history = prev.setdefault("history", [])
        history.append({"status": status.value, "ts": ts})
        _state[job_id] = prev

    # 写文件
    root = work_root or _work_root
    if root:
        progress_path = get_job_dir(job_id, root) / "logs" / "progress.json"
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        progress_path.write_text(
            json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def get_status(job_id: str) -> Optional[dict]:
    with _lock:
        return _state.get(job_id)
