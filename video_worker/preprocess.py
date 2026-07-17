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


def read_rotation(video_path: Path, ffmpeg_path: Path,
                  logger: Optional[logging.Logger] = None) -> int:
    """读 displaymatrix rotation，归一化到 0/90/180/270。仅供日志/调试，处理靠 ffmpeg 默认 autorotate。"""
    ff = str(ffmpeg_path.resolve())
    cmd = [ff, "-i", str(video_path), "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        return 0
    err = r.stderr.decode("utf-8", errors="replace")
    m = re.search(r"rotation of ([-\d.]+) degrees", err)
    if not m:
        return 0
    try:
        deg = float(m.group(1))
    except ValueError:
        return 0
    norm = round(deg / 90) * 90 % 360
    if norm != 0 and logger:
        logger.info(f"[rot] {video_path.name}: {deg}° (ffmpeg 默认 autorotate 会自动 bake)")
    return norm


def detect_orientation(video_path: Path, ffmpeg_path: Path,
                       logger: Optional[logging.Logger] = None) -> str:
    """抽中间帧判断横屏/竖屏。用 ffmpeg 默认 autorotate（旋转 metadata 会自动应用到帧上）。"""
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


def build_blur_background_vf(target_resolution: tuple[int, int],
                              blur_sigma: float = 25.0) -> str:
    """
    模糊背景填充的 -vf 字符串（用 split 复制输入流，避免 -filter_complex）。
    - 背景流：放大覆盖整个画面 + 高斯模糊
    - 前景流：等比缩放适应宽度
    - overlay 居中
    用 -vf 路径让 ffmpeg 默认 autorotate 自动把旋转 metadata bake 进像素。
    """
    w, h = target_resolution
    return (
        f"split[a][b];"
        f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma={blur_sigma}[bg];"
        f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )


def build_normalize_vf(target_resolution: tuple[int, int],
                       orientation: str,
                       strategy: ResizeStrategy = "blur_background",
                       blur_sigma: float = 25.0) -> str:
    """返回 -vf 滤镜字符串（所有策略都走 -vf 路径，让 ffmpeg 默认 autorotate 处理旋转 metadata）。

    方向匹配逻辑：
    - 源方向 == 目标方向（或源方向 unknown）：等比缩放 + 居中裁切铺满（无变形）。
    - 源方向 ≠ 目标方向：按 strategy 处理（blur_background / crop / letterbox）。
    """
    w, h = target_resolution
    target_orient = "horizontal" if w > h else "vertical"

    # 源方向 == 目标方向（或源方向未知）：等比缩放 + 居中裁切
    if orientation == target_orient or orientation == "unknown":
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h}"
        )

    # 源方向 ≠ 目标方向：按 strategy 处理
    if strategy == "blur_background":
        return build_blur_background_vf(target_resolution, blur_sigma)
    elif strategy == "crop":
        # 中央裁切（丢源画面较长的一边）
        if target_orient == "vertical":
            ar = w / h
            return f"crop=ih*{ar}:ih,scale={w}:{h}"
        else:
            ar = h / w
            return f"crop=iw:iw*{ar},scale={w}:{h}"
    elif strategy == "letterbox":
        # 等比缩放后黑边填充
        return (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"
        )
    else:
        return build_blur_background_vf(target_resolution, blur_sigma)


def normalize_one(src: Path, out: Path, ffmpeg_path: Path,
                  resolution: tuple[int, int] = (720, 1280),
                  fps: int = 25,
                  orientation: Optional[str] = None,
                  strategy: ResizeStrategy = "blur_background",
                  blur_sigma: float = 25.0,
                  logger: Optional[logging.Logger] = None) -> bool:
    """重编码到统一规格（去音轨）。
    所有策略统一走 -vf 路径，让 ffmpeg 默认 autorotate 自动把旋转 metadata bake 进像素。
    -filter_complex 路径不会自动应用 autorotate，且输出会保留 display matrix，
    所以改用 -vf split 复制输入流，绕开 -filter_complex 的限制。
    """
    ff = str(ffmpeg_path.resolve())
    if orientation is None:
        orientation = detect_orientation(src, ffmpeg_path, logger)

    read_rotation(src, ffmpeg_path, logger)  # 仅日志，让用户知道该 clip 有旋转

    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")

    vf = build_normalize_vf(resolution, orientation, strategy, blur_sigma)
    cmd = [
        ff, "-y", "-i", src_arg,
        "-vf", vf,
        # fast/18：preprocess 后续还要被 cut_clip + add_bgm 重编码 2 次，
        # 这里用较快 preset + 较高 CRF 节省时间，保留视觉无损质量
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
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
