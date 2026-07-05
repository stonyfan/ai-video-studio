"""
帧抓取：抽代表帧（50%）+ 三联图（25/50/75%）
"""
from __future__ import annotations
import logging
import subprocess
from pathlib import Path
from typing import Optional
from PIL import Image

from .validators import Scene


FRAME_W = 360
FRAME_H = 640


def grab_frame(src: Path, ts: float, out: Path, ffmpeg_path: Path,
               width: int = FRAME_W) -> bool:
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [str(ffmpeg_path), "-y", "-ss", f"{ts:.3f}", "-i", src_arg,
           "-vframes", "1", "-update", "1",
           "-vf", f"scale={width}:-1", "-q:v", "3", out_arg]
    subprocess.run(cmd, capture_output=True, timeout=30)
    return out.exists() and out.stat().st_size > 3000


def make_triplet(scene: Scene, ffmpeg_path: Path,
                 probe_dir: Path, extra_dir: Path, triplet_dir: Path,
                 logger: Optional[logging.Logger] = None) -> Optional[Path]:
    """为单个场景生成 25/50/75% 三联图"""
    sid = scene.id
    start, end = scene.start, scene.end
    dur = end - start
    if dur < 0.1:
        return None

    t25 = start + dur * 0.25
    t50 = start + dur * 0.50
    t75 = start + dur * 0.75

    probe_dir.mkdir(parents=True, exist_ok=True)
    extra_dir.mkdir(parents=True, exist_ok=True)
    triplet_dir.mkdir(parents=True, exist_ok=True)

    f50 = probe_dir / f"{sid}.jpg"
    f25 = extra_dir / f"{sid}_25.jpg"
    f75 = extra_dir / f"{sid}_75.jpg"

    if not (f50.exists() and f50.stat().st_size > 3000):
        grab_frame(scene.src, t50, f50, ffmpeg_path)
    if not (f25.exists() and f25.stat().st_size > 3000):
        grab_frame(scene.src, t25, f25, ffmpeg_path)
    if not (f75.exists() and f75.stat().st_size > 3000):
        grab_frame(scene.src, t75, f75, ffmpeg_path)

    out = triplet_dir / f"{sid}.jpg"
    if out.exists() and out.stat().st_size > 10000:
        return out

    imgs = []
    for f in [f25, f50, f75]:
        if not (f.exists() and f.stat().st_size > 3000):
            return None
        imgs.append(Image.open(f).resize((FRAME_W, FRAME_H)))

    canvas = Image.new("RGB", (FRAME_W * 3 + 20, FRAME_H), (20, 20, 20))
    canvas.paste(imgs[0], (0, 0))
    canvas.paste(imgs[1], (FRAME_W + 10, 0))
    canvas.paste(imgs[2], (FRAME_W * 2 + 20, 0))
    canvas.save(out, quality=85)
    return out


def make_triplets(scenes: list[Scene], job_dir: Path,
                  ffmpeg_path: Path,
                  logger: Optional[logging.Logger] = None) -> dict[str, Path]:
    """
    批量生成三联图
    返回：{scene_id: triplet_path}
    """
    probe_dir = job_dir / "work" / "frames"
    extra_dir = job_dir / "work" / "frames_extra"
    triplet_dir = job_dir / "work" / "triplets"

    out = {}
    for sc in scenes:
        path = make_triplet(sc, ffmpeg_path, probe_dir, extra_dir, triplet_dir, logger)
        if path:
            out[sc.id] = path
    if logger:
        logger.info(f"[triplets] 完成 {len(out)}/{len(scenes)}")
    return out
