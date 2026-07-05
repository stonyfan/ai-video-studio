"""
编排：拍摄时序 + 节拍对齐 + BGM 选 BGM 后吸附
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

from .validators import AnalyzedScene, Storyboard, StoryboardItem, JobConfig


def compute_cut(start: float, end: float, best_frame: str,
                cut_duration: float) -> tuple[float, float]:
    """根据 best_frame 计算切片位置"""
    D = end - start
    cut = min(cut_duration, D)
    if best_frame == "left":
        return start, start + cut
    elif best_frame == "right":
        return end - cut, end
    else:  # mid
        mid = (start + end) / 2
        return max(start, mid - cut / 2), min(end, mid + cut / 2)


def snap_to_beat(t: float, beats: list[float], max_adj: float = 0.30) -> float:
    """吸附到最近 beat"""
    if not beats:
        return t
    nearest = min(beats, key=lambda b: abs(b - t))
    return nearest if abs(nearest - t) <= max_adj else t


def deduplicate(analyzed: list[AnalyzedScene]) -> list[AnalyzedScene]:
    """
    跨场景去重：同 main_object + 同 action_type 只留一个（按 cut_duration 长优先）
    """
    seen: dict[tuple[str, str], AnalyzedScene] = {}
    for a in analyzed:
        key = (a.main_object, a.action_type)
        if not a.main_object:  # 缺描述不过滤
            continue
        prev = seen.get(key)
        if prev is None or a.cut_duration > prev.cut_duration:
            seen[key] = a
    kept_ids = {v.id for v in seen.values()}
    # 保留顺序；没有 main_object 的也保留
    return [a for a in analyzed if a.id in kept_ids or not a.main_object]


def plan(analyzed: list[AnalyzedScene], config: JobConfig,
         beats: Optional[list[float]] = None,
         target_duration: Optional[int] = None,
         logger: Optional[logging.Logger] = None) -> Storyboard:
    """
    生成 storyboard：
    - 拍摄时序（按 scene.id 字典序，含子序号）
    - cut_duration 来自 analyzed
    - us/ue 吸附到 beats
    """
    target = target_duration or config.target_duration

    # 按拍摄时序排序（seg + sc_idx）
    sorted_scenes = sorted(analyzed, key=lambda a: _natural_key(a.id))

    # 去重（可选）
    sorted_scenes = deduplicate(sorted_scenes)
    if logger:
        logger.info(f"[plan] 去重后 {len(sorted_scenes)} 个场景")

    selected = []
    total = 0.0
    for i, sc in enumerate(sorted_scenes, 1):
        us, ue = compute_cut(sc.start, sc.end, sc.best_frame, sc.cut_duration)
        us = snap_to_beat(us, beats or [])
        ue = snap_to_beat(ue, beats or [])
        if ue <= us + 0.3:
            ue = us + 0.5
        dur = ue - us
        selected.append(StoryboardItem(
            order=i,
            id=sc.id,
            cut_duration=round(dur, 3),
            subtitle=None,
            use_start=round(us, 3),
            use_end=round(ue, 3),
            reason=sc.best_moment,
        ))
        total += dur

    board = Storyboard(
        narrative=f"按拍摄时序，{len(selected)} 个瞬时",
        target_duration_sec=target,
        expected_duration_sec=round(total, 2),
        selected=selected,
    )
    if logger:
        logger.info(f"[plan] storyboard 完成: {len(selected)} 个瞬时, 预期 {total:.2f}s")
    return board


def save_storyboard(board: Storyboard, job_dir: Path) -> Path:
    out = job_dir / "work" / "storyboard.json"
    out.write_text(
        json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out


def _natural_key(s: str) -> list:
    import re
    parts = re.split(r"[_-]", s)
    return [int(t) if t.isdigit() else t
            for piece in parts
            for t in re.split(r'(\d+)', piece) if t]
