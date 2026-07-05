"""
预处理：检测方向 + 重编码到统一规格（720×1280 竖屏默认）

支持的横屏转竖屏策略（resize_strategy）：
- crop：中央裁切（丢左右）
- letterbox：上下黑边
- blur_background：模糊背景填充（默认，抖音/小红书主流）
"""
from __future__ import annotations
import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Optional
from PIL import Image

from .validators import JobConfig


ResizeStrategy = Literal["crop", "letterbox", "blur_background"]


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


def build_normalize_vf(target_resolution: tuple[int, int],
                       orientation: str,
                       strategy: ResizeStrategy = "blur_background") -> Optional[str]:
    """
    返回 -vf 滤镜字符串。
    blur_background 策略返回 None（需要 -filter_complex，由 normalize_one 特殊处理）。
    """
    w, h = target_resolution
    if orientation != "horizontal":
        # 竖屏：直接 scale（无论 strategy）
        return f"scale={w}:{h}:flags=lanczos"

    # 横屏
    if strategy == "crop":
        return f"crop=ih*9/16:ih,scale={w}:{h}:flags=lanczos"
    elif strategy == "letterbox":
        return f"scale={w}:-1,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
    elif strategy == "blur_background":
        return None  # 走 filter_complex
    else:
        return f"scale={w}:{h}:flags=lanczos"


def build_blur_background_complex(target_resolution: tuple[int, int],
                                   blur_sigma: float = 25.0) -> str:
    """
    模糊背景填充的 -filter_complex 字符串
    - 背景流：放大覆盖整个画面 + 高斯模糊
    - 前景流：等比缩放适应宽度
    - overlay 居中
    """
    w, h = target_resolution
    return (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma={blur_sigma}[bg];"
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
    )


def normalize_one(src: Path, out: Path, ffmpeg_path: Path,
                  resolution: tuple[int, int] = (720, 1280),
                  fps: int = 25,
                  orientation: Optional[str] = None,
                  strategy: ResizeStrategy = "blur_background",
                  blur_sigma: float = 25.0,
                  logger: Optional[logging.Logger] = None) -> bool:
    """重编码到统一规格（去音轨）"""
    ff = str(ffmpeg_path.resolve())
    if orientation is None:
        orientation = detect_orientation(src, ffmpeg_path, logger)

    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")

    base_cmd = [
        ff, "-y", "-i", src_arg,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", "-r", str(fps),
    ]

    vf = build_normalize_vf(resolution, orientation, strategy)
    if vf:
        # 简单 -vf 模式
        cmd = base_cmd + ["-vf", vf, out_arg]
    else:
        # blur_background：用 -filter_complex
        fc = build_blur_background_complex(resolution, blur_sigma)
        cmd = base_cmd + ["-filter_complex", fc, "-map", "[v]", out_arg]

    r = subprocess.run(cmd, capture_output=True, timeout=900)
    ok = r.returncode == 0 and out.exists() and out.stat().st_size > 5000
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"重编码失败 {src.name}: {err}")
    return ok


def normalize(srcs: list[Path], job_dir: Path, config: JobConfig,
              resolution: tuple[int, int] = (720, 1280),
              fps: int = 25,
              strategy: ResizeStrategy = "blur_background",
              blur_sigma: float = 25.0,
              ffmpeg_path: Optional[Path] = None,
              logger: Optional[logging.Logger] = None) -> list[Path]:
    """批量重编码。输出：job_dir/work/clips/<stem>.mp4"""
    ff = ffmpeg_path or config.ffmpeg_path
    clips_dir = job_dir / "work" / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    if logger:
        logger.info(f"[preprocess] strategy={strategy}, blur_sigma={blur_sigma}")

    outs = []
    for src in srcs:
        out = clips_dir / f"{src.stem}.mp4"
        if out.exists() and out.stat().st_size > 100000:
            if logger:
                logger.info(f"[skip] {src.stem} 已存在")
            outs.append(out)
            continue
        ok = normalize_one(src, out, ff, resolution, fps,
                          strategy=strategy, blur_sigma=blur_sigma,
                          logger=logger)
        if ok:
            outs.append(out)
            if logger:
                logger.info(f"[ok] {src.stem} ({out.stat().st_size // 1024} KB)")
    return outs
