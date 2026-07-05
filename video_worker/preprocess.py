"""
预处理：检测方向 + 重编码到统一规格（720×1280 竖屏默认）

横屏素材：先 crop 中央 9:16 区域，再 scale（保留宽高比，不变形）
竖屏素材：直接 scale
"""
from __future__ import annotations
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from PIL import Image

from .validators import JobConfig


def detect_orientation(video_path: Path, ffmpeg_path: Path,
                       logger: Optional[logging.Logger] = None) -> str:
    """抽中间帧判断横屏/竖屏（不信任 ffprobe rotation 元数据）"""
    ff = str(ffmpeg_path.resolve())
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        cmd = [ff, "-y", "-ss", "1", "-i", str(video_path),
               "-vframes", "1", "-update", "1", str(tmp_path)]
        subprocess.run(cmd, capture_output=True, timeout=30)
        if not tmp_path.exists():
            return "unknown"
        with Image.open(tmp_path) as im:
            w, h = im.size
        return "vertical" if h > w else "horizontal"
    except Exception as e:
        if logger:
            logger.warning(f"方向检测失败 {video_path.name}: {e}")
        return "unknown"
    finally:
        tmp_path.unlink(missing_ok=True)


def get_duration(video_path: Path, ffmpeg_path: Path) -> float:
    """ffprobe 风格读时长"""
    ff = str(ffmpeg_path.resolve())
    cmd = [ff, "-i", str(video_path), "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    err = r.stderr.decode("utf-8", errors="replace")
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
    if m:
        h, mn, s = m.groups()
        return int(h) * 3600 + int(mn) * 60 + float(s)
    return 0.0


def build_normalize_filter(target_resolution: tuple[int, int],
                           orientation: str) -> str:
    """
    根据方向构建滤镜：
    - vertical：直接 scale（已是 9:16）
    - horizontal：crop 中央 9:16 区域 + scale
    - unknown：按 vertical 处理（兜底）
    """
    w, h = target_resolution
    if orientation == "horizontal":
        # 横屏 → 中央裁切 9:16 区域（保留高度，宽度 = h_orig * 9/16）
        # crop=iw*9/16:ih 也可以，但用 ih 更直观
        # ih*9/16 = 宽度（按 9:16 比例）
        return f"crop=ih*9/16:ih,scale={w}:{h}:flags=lanczos"
    else:
        # vertical / unknown → 直接 scale
        return f"scale={w}:{h}:flags=lanczos"


def normalize_one(src: Path, out: Path, ffmpeg_path: Path,
                  resolution: tuple[int, int] = (720, 1280),
                  fps: int = 25, orientation: Optional[str] = None,
                  logger: Optional[logging.Logger] = None) -> bool:
    """重编码到统一规格（去音轨）"""
    ff = str(ffmpeg_path.resolve())
    if orientation is None:
        orientation = detect_orientation(src, ffmpeg_path, logger)

    vf = build_normalize_filter(resolution, orientation)

    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [
        ff, "-y", "-i", src_arg,
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", "-r", str(fps),
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    ok = r.returncode == 0 and out.exists() and out.stat().st_size > 5000
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"重编码失败 {src.name}: {err}")
    return ok


def normalize(srcs: list[Path], job_dir: Path, config: JobConfig,
              resolution: tuple[int, int] = (720, 1280),
              fps: int = 25,
              ffmpeg_path: Optional[Path] = None,
              logger: Optional[logging.Logger] = None) -> list[Path]:
    """批量重编码。输出：job_dir/work/clips/<stem>.mp4"""
    ff = ffmpeg_path or config.ffmpeg_path
    clips_dir = job_dir / "work" / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    outs = []
    for src in srcs:
        out = clips_dir / f"{src.stem}.mp4"
        if out.exists() and out.stat().st_size > 100000:
            if logger:
                logger.info(f"[skip] {src.stem} 已存在")
            outs.append(out)
            continue
        ok = normalize_one(src, out, ff, resolution, fps, logger=logger)
        if ok:
            outs.append(out)
            if logger:
                logger.info(f"[ok] {src.stem} ({out.stat().st_size // 1024} KB)")
    return outs
