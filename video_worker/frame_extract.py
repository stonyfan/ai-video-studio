"""
帧抓取：抽代表帧（50%）+ 三联图（25/50/75%）+ 多帧序列（替代三联图）
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

# 多帧模式分辨率（比三联图单帧高，因为不再横排拼接）
MULTI_FRAME_W = 540
MULTI_FRAME_H = 960


def grab_frame(src: Path, ts: float, out: Path, ffmpeg_path: Path,
               width: int = FRAME_W) -> bool:
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [str(ffmpeg_path), "-y", "-ss", f"{ts:.3f}", "-i", src_arg,
           "-vframes", "1", "-update", "1",
           "-vf", f"scale={width}:-1", "-q:v", "3", out_arg]
    subprocess.run(cmd, capture_output=True, timeout=30)
    return out.exists() and out.stat().st_size > 3000


def grab_frame_hq(src: Path, ts: float, out: Path, ffmpeg_path: Path,
                  width: int = MULTI_FRAME_W, height: int = MULTI_FRAME_H) -> bool:
    """高分辨率抽帧（多帧模式用）。强制缩放到 width x height（cover 模式）。"""
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    # scale + crop 强制成指定尺寸（避免比例失真）
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
          f"crop={width}:{height}")
    cmd = [str(ffmpeg_path), "-y", "-ss", f"{ts:.3f}", "-i", src_arg,
           "-vframes", "1", "-update", "1",
           "-vf", vf, "-q:v", "3", out_arg]
    subprocess.run(cmd, capture_output=True, timeout=30)
    return out.exists() and out.stat().st_size > 3000


def _adaptive_frame_count(dur: float, min_n: int = 5, max_n: int = 12,
                          factor: float = 1.5) -> int:
    """按场景时长决定抽多少帧：1s→5, 5s→8, 8s+→12。"""
    n = int(dur * factor)
    return max(min_n, min(max_n, n))


def make_frames(scene: Scene, ffmpeg_path: Path,
                frames_dir: Path,
                logger: Optional[logging.Logger] = None) -> list[Path]:
    """为单个场景抽 N 帧序列（替代三联图）。
    自适应帧数：clip(int(dur*1.5), 5, 12) — 1s 场景 5 帧，5s 场景 8 帧，8s+ 12 帧。
    抽帧时间点：均匀分布在 [start, end]，端点包含。
    返回：成功抽到的帧 Path 列表（按时间顺序）。
    """
    sid = scene.id
    start, end = scene.start, scene.end
    dur = end - start
    if dur < 0.1:
        return []

    frames_dir.mkdir(parents=True, exist_ok=True)
    n = _adaptive_frame_count(dur)
    timestamps = [start + dur * i / (n - 1) if n > 1 else start + dur / 2
                  for i in range(n)]

    paths: list[Path] = []
    for i, ts in enumerate(timestamps):
        fp = frames_dir / f"{sid}_f{i:02d}.jpg"
        if not (fp.exists() and fp.stat().st_size > 3000):
            grab_frame_hq(scene.src, ts, fp, ffmpeg_path)
        if fp.exists() and fp.stat().st_size > 3000:
            paths.append(fp)

    if logger and len(paths) < n:
        logger.warning(f"[frames] {sid} 期望 {n} 帧，实际抽到 {len(paths)} 帧")
    return paths


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
                  multi_sample_min_sec: float = 4.0,
                  logger: Optional[logging.Logger] = None
                  ) -> tuple[dict[str, Path], list[Scene]]:
    """
    批量生成三联图：每个 scene 一个 triplet。

    历史上有"长场景拆前后两半"的二次切分（multi_sample_min_sec），但自 scene_detect
    引入 max_scene_len_sec=8 强切后，进入本函数的 scene 已经是独立短场景，无需再切。
    保留 multi_sample_min_sec 参数仅为兼容调用方签名，内部不再使用。

    返回：
    - triplets_dict: {scene_id: triplet_path}
    - analysis_scenes: 与 triplets_dict 一一对应的 Scene 列表
    """
    probe_dir = job_dir / "work" / "frames"
    extra_dir = job_dir / "work" / "frames_extra"
    triplet_dir = job_dir / "work" / "triplets"

    triplets: dict[str, Path] = {}
    analysis_scenes: list[Scene] = []

    for sc in scenes:
        if sc.end - sc.start < 0.1:
            continue
        path = make_triplet(sc, ffmpeg_path, probe_dir, extra_dir, triplet_dir, logger)
        if path:
            triplets[sc.id] = path
            analysis_scenes.append(sc)

    if logger:
        logger.info(f"[triplets] 完成 {len(triplets)}/{len(scenes)} 场景")
    return triplets, analysis_scenes


def make_frames_batch(scenes: list[Scene], job_dir: Path,
                      ffmpeg_path: Path,
                      logger: Optional[logging.Logger] = None
                      ) -> tuple[dict[str, list[Path]], list[Scene]]:
    """批量生成多帧序列：每个 scene 一组 N 帧。

    替代 make_triplets 用于多帧模式。每帧单独保存（不拼接），
    分辨率 540×960，按时间顺序命名 f00..fNN。

    返回：
    - frames_dict: {scene_id: [path1, path2, ...]}（按时间顺序）
    - analysis_scenes: 与 frames_dict 一一对应的 Scene 列表
    """
    frames_root = job_dir / "work" / "frames_seq"

    frames_dict: dict[str, list[Path]] = {}
    analysis_scenes: list[Scene] = []

    for sc in scenes:
        if sc.end - sc.start < 0.1:
            continue
        paths = make_frames(sc, ffmpeg_path, frames_root, logger)
        if paths:
            frames_dict[sc.id] = paths
            analysis_scenes.append(sc)

    if logger:
        total_frames = sum(len(v) for v in frames_dict.values())
        avg_n = total_frames / len(frames_dict) if frames_dict else 0
        logger.info(f"[frames_seq] 完成 {len(frames_dict)}/{len(scenes)} 场景，"
                    f"共 {total_frames} 帧（avg {avg_n:.1f}/scene）")
    return frames_dict, analysis_scenes
