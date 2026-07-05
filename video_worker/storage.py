"""
任务工作目录管理：jobs/<job_id>/{input,work,frames,triplets,logs,output}
"""
from __future__ import annotations
import logging
import shutil
import sys
from pathlib import Path

from .validators import JobConfig


WORK_SUBDIRS = ["input", "work/clips", "work/frames", "work/triplets",
                "logs", "output"]


def get_job_dir(job_id: str, work_root: Path) -> Path:
    return Path(work_root) / job_id


def create_job_dir(job_id: str, work_root: Path, *, clean_if_exists: bool = False) -> Path:
    """创建任务目录；可选清理已有目录"""
    job_dir = get_job_dir(job_id, work_root)
    if job_dir.exists() and clean_if_exists:
        shutil.rmtree(job_dir)
    for sub in WORK_SUBDIRS:
        (job_dir / sub).mkdir(parents=True, exist_ok=True)
    return job_dir


def setup_logger(job_id: str, job_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """给单个 job 配独立 logger（写文件 + stdout，UTF-8）"""
    logger = logging.getLogger(f"job.{job_id}")
    logger.setLevel(level)
    # 防止重复 handler（多次调用）
    for h in list(logger.handlers):
        logger.removeHandler(h)

    log_path = job_dir / "logs" / "job.log"
    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter(f"[{job_id}] %(message)s"))
    logger.addHandler(sh)
    return logger


def get_log_path(job_dir: Path) -> Path:
    return job_dir / "logs" / "job.log"


def get_output_path(job_dir: Path, *, filename: str = "final.mp4") -> Path:
    return job_dir / "output" / filename


def cleanup_work(job_dir: Path, keep_output: bool = True) -> None:
    """任务完成后清理中间产物，保留 output/ 和 logs/"""
    work = job_dir / "work"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)


def check_disk_space(work_root: Path, min_gb: float = 5.0) -> tuple[bool, float]:
    """检查 work_root 所在盘可用空间"""
    try:
        usage = shutil.disk_usage(work_root.parent if work_root.exists() else work_root)
        free_gb = usage.free / 1024**3
        return free_gb >= min_gb, free_gb
    except Exception:
        return True, -1.0
