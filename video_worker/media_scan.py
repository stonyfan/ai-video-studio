"""
素材扫描：扫描目录，过滤视频文件
"""
from __future__ import annotations
import logging
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v", ".3gp"}


def scan_videos(input_path: Path, logger: Optional[logging.Logger] = None) -> list[Path]:
    """扫描素材目录，返回按文件名排序的视频文件列表"""
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"素材路径不存在: {input_path}")
    if input_path.is_file():
        if input_path.suffix.lower() in VIDEO_EXTS:
            return [input_path]
        raise ValueError(f"非视频文件: {input_path}")

    # 目录扫描
    files = []
    for f in input_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTS:
            files.append(f)

    # 按文件名自然排序（数字优先）
    files.sort(key=lambda p: _natural_key(p.name))

    if logger:
        logger.info(f"扫描到 {len(files)} 个视频文件 in {input_path}")
        for f in files[:5]:
            logger.debug(f"  - {f.name}")
        if len(files) > 5:
            logger.debug(f"  ... 还有 {len(files) - 5} 个")

    if not files:
        raise ValueError(f"目录中没有视频文件: {input_path}")

    return files


def _natural_key(s: str) -> list:
    """自然排序键：'1-1' → [0, '1', '-', '1']"""
    import re
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]
