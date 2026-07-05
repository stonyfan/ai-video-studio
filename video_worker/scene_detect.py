"""
场景切分：PySceneDetect ContentDetector
"""
from __future__ import annotations
import json
import logging
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
                 logger: Optional[logging.Logger] = None) -> list[Scene]:
    """
    对每个 clip 跑场景切分，返回 Scene 列表
    """
    if open_video is None:
        raise ImportError("scenedetect 未安装，请 pip install scenedetect[opencv]")

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
