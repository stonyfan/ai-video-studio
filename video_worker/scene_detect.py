"""
场景切分：PySceneDetect ContentDetector
"""
from __future__ import annotations
import json
import logging
import math
import re
import subprocess
from pathlib import Path
from typing import Optional

from .validators import Scene

try:
    from scenedetect import open_video, SceneManager, ContentDetector
except ImportError:
    open_video = None  # scenedetect 未装时也不影响 import


def split_scenes(clips: list[Path], job_dir: Path,
                 ffmpeg_path: Path,
                 threshold: float = 27.0,
                 min_len_sec: float = 0.4,
                 max_scene_len_sec: float = 12.0,
                 logger: Optional[logging.Logger] = None) -> list[Scene]:
    """
    对每个 clip 跑场景切分，返回 Scene 列表。
    resume 友好：如果 work/scenes.json 存在且覆盖了所有 clip 的 stem，直接读回。

    max_scene_len_sec > 0 时，任何长度超过该值的场景（含 ContentDetector 兜底整段）
    会被强制均分为 ceil(dur/max) 段。默认 12s（早期 8s 切得太碎，对航拍/连续镜头过度
    切分）。真正理想是按内容变化分布切，但实现复杂，目前用固定窗口兜底。
    """
    if open_video is None:
        raise ImportError("scenedetect 未安装，请 pip install scenedetect[opencv]")

    # resume 命中：scenes.json 已覆盖所有 clips
    out_path = job_dir / "work" / "scenes.json"
    if out_path.exists():
        try:
            cached = json.loads(out_path.read_text(encoding="utf-8"))
            existing = [Scene(**s) for s in cached]
            existing_stems = {c.src.stem for c in existing}
            needed_stems = {c.stem for c in clips}
            if needed_stems.issubset(existing_stems):
                if logger:
                    logger.info(f"[scene] 命中缓存 {len(existing)} 场景，跳过切分")
                return existing
            if logger:
                logger.info(f"[scene] 部分命中缓存（{len(existing)} 已有），继续切分缺失的")
        except Exception as e:
            if logger:
                logger.warning(f"[scene] 读 scenes.json 失败，重新切分: {e}")

    scenes_dict: dict[str, Scene] = []

    for clip in clips:
        seg_id = clip.stem
        try:
            video = open_video(str(clip))
            sm = SceneManager()
            sm.add_detector(ContentDetector(threshold=threshold))
            sm.detect_scenes(video)
            scene_list = sm.get_scene_list()
        except Exception as e:
            if logger:
                logger.error(f"[scene] 切分失败 {seg_id}: {e}")
            continue

        kept = []
        for i, (start_tc, end_tc) in enumerate(scene_list):
            start = start_tc.get_seconds()
            end = end_tc.get_seconds()
            if end - start >= min_len_sec:
                kept.append((i, start, end, end - start))

        # 整段当成 1 个场景（兜底）
        if not kept:
            dur = _get_duration(clip, ffmpeg_path)
            if dur > 0:
                kept = [(0, 0.0, dur, dur)]

        # A: 长场景强制再切，保证素材丰富度
        # 航拍/宣传片等连续镜头常被 ContentDetector 视为单场景，
        # 这里按 max_scene_len_sec 强制均分，让后续 storyboard 有更多片段可选
        if max_scene_len_sec and max_scene_len_sec > 0:
            split_kept = []
            for sc_idx, start, end, dur in kept:
                if dur > max_scene_len_sec:
                    n = max(2, math.ceil(dur / max_scene_len_sec))
                    sub_dur = dur / n
                    added = 0
                    for i in range(n):
                        s = start + i * sub_dur
                        e = min(start + (i + 1) * sub_dur, end)
                        if e - s >= min_len_sec:
                            # sc_idx * 1000 + i 保证唯一且可读（如 0_001/0_002）
                            split_kept.append((sc_idx * 1000 + i, s, e, e - s))
                            added += 1
                    if logger:
                        logger.info(f"[scene] {seg_id} 场景 {sc_idx} "
                                    f"dur={dur:.1f}s > {max_scene_len_sec}s，强切为 {added} 段")
                else:
                    split_kept.append((sc_idx, start, end, dur))
            kept = split_kept

        for sc_idx, start, end, dur in kept:
            scene_id = f"{seg_id}_{sc_idx}"
            scenes_dict.append(Scene(
                id=scene_id,
                src=clip,
                seg=seg_id,
                sc_idx=sc_idx,
                start=round(start, 3),
                end=round(end, 3),
                dur=round(dur, 3),
            ))

        if logger:
            logger.info(f"[scene] {seg_id} 切出 {len(kept)} 个场景")

    # 持久化
    out_path = job_dir / "work" / "scenes.json"
    out_path.write_text(
        json.dumps([s.model_dump() for s in scenes_dict], ensure_ascii=False, indent=2,
                   default=str),
        encoding="utf-8",
    )
    return scenes_dict


def _get_duration(clip: Path, ffmpeg_path: Path) -> float:
    cmd = [str(ffmpeg_path), "-i", str(clip), "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    err = r.stderr.decode("utf-8", errors="replace")
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
    if m:
        h, mn, s = m.groups()
        return int(h) * 3600 + int(mn) * 60 + float(s)
    return 0.0
