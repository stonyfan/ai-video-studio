"""
候选池分流：把 AnalyzedScene 按 P3 评分分成 keep / maybe / discard 三档。

规则（默认阈值）：
- bad_reason 非空 + visual_quality <= 3       → discard（画质太差）
- bad_reason 非空 + highlight_score <= 4      → discard（无高光且有问题）
- score >= 7 + bad_reason 空                  → keep
- 5 <= score < 7 + bad_reason 空              → maybe
- 其他（score < 5 等）                         → discard

阈值集中在 configs/default.yaml 的 candidate_pool 段，可在不改代码的情况下调参。
"""
from __future__ import annotations
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .validators import (
    AnalyzedScene, JobConfig, CandidateClip, CandidatePool,
)
from .storyboard import compute_score


DEFAULT_RULES = {
    "keep_score_min": 7.0,
    "maybe_score_min": 5.0,
    "discard_visual_max": 3,
    "discard_highlight_max": 4,
    # action_type 命中此列表 → 强制 discard（拍摄转场/装备调整，无叙事价值）
    "discard_actions": ["walking"],
}


def _classify_one(sc: AnalyzedScene, rules: dict) -> tuple[str, float, str]:
    """对单个 AnalyzedScene 返回 (status, score, reason)。"""
    score = compute_score(sc)
    has_bad = bool(sc.bad_reason and sc.bad_reason.strip())

    # action_type 黑名单（拍摄转场/装备调整等无叙事价值）→ 直接 discard
    discard_actions = rules.get("discard_actions") or []
    if sc.action_type in discard_actions:
        return "discard", score, f"action={sc.action_type} 在 discard_actions 黑名单 → discard"

    if has_bad:
        if sc.visual_quality <= rules["discard_visual_max"]:
            return "discard", score, f"bad_reason={sc.bad_reason!r} visual={sc.visual_quality} → discard"
        if sc.highlight_score <= rules["discard_highlight_max"]:
            return "discard", score, f"bad_reason={sc.bad_reason!r} highlight={sc.highlight_score} → discard"

    if has_bad:
        # 有 bad_reason 但视觉/高光都还行 → 降级到 maybe 保守处理
        return "maybe", score, f"bad_reason={sc.bad_reason!r} 但视觉尚可 → maybe"

    if score >= rules["keep_score_min"]:
        return "keep", score, f"score={score:.1f} (hl={sc.highlight_score} vis={sc.visual_quality}) → keep"

    if score >= rules["maybe_score_min"]:
        return "maybe", score, f"score={score:.1f} (hl={sc.highlight_score} vis={sc.visual_quality}) → maybe"

    return "discard", score, f"score={score:.1f} 过低 → discard"


def classify(analyzed: list[AnalyzedScene],
             rules: Optional[dict] = None,
             job_id: str = "",
             logger: Optional[logging.Logger] = None) -> CandidatePool:
    """批量分流。rules 为空时用 DEFAULT_RULES。"""
    rules = {**DEFAULT_RULES, **(rules or {})}
    keep, maybe, discard = [], [], []
    for sc in analyzed:
        status, score, reason = _classify_one(sc, rules)
        clip = CandidateClip(
            id=sc.id, status=status, score=round(score, 2),
            reason=reason, analyzed=sc,
        )
        if status == "keep":
            keep.append(clip)
        elif status == "maybe":
            maybe.append(clip)
        else:
            discard.append(clip)

    if logger:
        logger.info(
            f"[candidate_pool] {len(analyzed)} 段 → keep={len(keep)} "
            f"maybe={len(maybe)} discard={len(discard)} (rules={rules})"
        )

    return CandidatePool(
        job_id=job_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
        keep=keep, maybe=maybe, discard=discard,
        rule_summary=rules,
    )


def save_pool(pool: CandidatePool, job_dir: Path) -> Path:
    """落盘到 work/candidate_pool.json"""
    out = job_dir / "work" / "candidate_pool.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(pool.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out
