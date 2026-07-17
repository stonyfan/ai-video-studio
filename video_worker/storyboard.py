"""
编排：
- timeline 模式：creation_time 排序 + per-src 去重 + 算法截断
- llm 模式：LLM 故事阶段聚类 + 阶段序 + 公平时长分配
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
    """吸附到最近 beat（保留接口，plan 当前不调用）。"""
    if not beats:
        return t
    nearest = min(beats, key=lambda b: abs(b - t))
    return nearest if abs(nearest - t) <= max_adj else t


def _jaccard(a: set[str], b: set[str]) -> float:
    """两个集合的 Jaccard 相似度"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


# 综合评分权重（P3 镜头评分系统）
SCORE_WEIGHTS = {"highlight": 0.5, "visual": 0.3, "motion": 0.2}
BAD_PENALTY = 0.5

STORY_ROLE_PRIORITY = {
    "climax": 0,
    "opening": 1,
    "ending": 2,
    "process": 3,
    "broll": 4,
}


def _strip_negation(hint: str) -> str:
    """去掉"弱化 X"片段，避免否定词干扰正向关键词识别。
    例如 "特写镜头优先，弱化全景" -> "特写镜头优先，"
    """
    import re
    return re.sub(r"弱化[^，。、,\.]*", "", hint or "")


def weights_from_style_hint(hint: str) -> dict[str, float]:
    """根据 style_hint 关键词返回 SCORE_WEIGHTS。多变体生成时让选段真的差异化。"""
    raw = hint or ""
    h = _strip_negation(raw).lower()
    if not raw:
        return dict(SCORE_WEIGHTS)
    # 动作/运镜类：motion 权重大幅抬高
    if "动作密集" in h or "运镜" in h or "motion_score" in h or "动态" in h:
        return {"highlight": 0.3, "visual": 0.1, "motion": 0.6}
    # 色彩/构图/画质类：visual 权重大幅抬高
    if "色彩" in h or "构图" in h or "对称" in h or "visual_quality" in h or "画质" in h:
        return {"highlight": 0.3, "visual": 0.6, "motion": 0.1}
    # opening/广角/全景：visual + highlight 提升，motion 弱化
    if "opening" in h or "广角" in h or "全景" in h:
        return {"highlight": 0.4, "visual": 0.5, "motion": 0.1}
    # 特写：highlight 主导
    if "特写" in h:
        return {"highlight": 0.6, "visual": 0.3, "motion": 0.1}
    return dict(SCORE_WEIGHTS)


def role_boost_from_style_hint(hint: str) -> dict[str, float]:
    """story_role 加权（叠加在 compute_score 上）。让 hint 真的影响 role 选择。"""
    raw = hint or ""
    h = _strip_negation(raw).lower()
    boost = {r: 0.0 for r in STORY_ROLE_PRIORITY}
    if not raw:
        return boost
    if "opening" in h or "广角" in h:
        boost["opening"] = 2.0
    if "climax 集中" in h or "climax后置" in h or "climax 后置" in h:
        boost["climax"] = 1.5
    if "氛围" in h or "慢剪" in h:
        boost["broll"] = 0.8
    if "故事推进" in h:
        boost["opening"] = 1.0
        boost["climax"] = 1.0
    return boost


def cut_range_from_style_hint(hint: str, base: tuple[float, float]) -> tuple[float, float]:
    """根据 style_hint 调整 cut_duration_range。短切 hint → 短；长放 hint → 长。"""
    h = (hint or "").lower()
    if not hint:
        return base
    if "短切" in h:
        return (0.5, 0.9)
    if "长放" in h:
        return (1.3, 2.0)
    return base


def compute_score(sc: AnalyzedScene,
                  weights: Optional[dict[str, float]] = None,
                  role_boost: Optional[dict[str, float]] = None) -> float:
    """综合评分，weights/role_boost 用于多变体差异化。bad_reason 非空降权。"""
    w = weights or SCORE_WEIGHTS
    base = (
        sc.highlight_score * w.get("highlight", 0.5)
        + sc.visual_quality * w.get("visual", 0.3)
        + sc.motion_score * w.get("motion", 0.2)
    )
    if role_boost:
        base += role_boost.get(sc.story_role, 0.0)
    if sc.bad_reason:
        base *= BAD_PENALTY
    return base


def story_role_priority(sc: AnalyzedScene) -> int:
    return STORY_ROLE_PRIORITY.get(sc.story_role, 3)


def compute_novelty(sc: AnalyzedScene,
                    all_scenes: list[AnalyzedScene]) -> float:
    """sc 相对于 all_scenes 中其他段的平均 dissimilarity（1 - avg_jaccard）。"""
    sc_set = set(sc.main_objects)
    if not sc_set:
        return 1.0
    jacs = []
    for other in all_scenes:
        if other.id == sc.id:
            continue
        other_set = set(other.main_objects)
        if not other_set:
            continue
        jacs.append(_jaccard(sc_set, other_set))
    if not jacs:
        return 1.0
    avg_jac = sum(jacs) / len(jacs)
    return 1.0 - avg_jac


def deduplicate(analyzed: list[AnalyzedScene],
                threshold: float = 0.7,
                time_decay_sec: float = 10.0,
                logger: Optional[logging.Logger] = None
                ) -> tuple[list[AnalyzedScene], list[AnalyzedScene]]:
    """
    per-src 去重：只在同一源视频内做重复判定。
    判定条件（全部满足才判重复）：
    1. main_objects Jaccard ≥ threshold
    2. best_moment 任一为空 OR 两者相同
    3. 时间中点距离 ≤ time_decay_sec
    """
    by_src: dict = {}
    srcs_order: list = []
    for sc in analyzed:
        if sc.src not in by_src:
            by_src[sc.src] = []
            srcs_order.append(sc.src)
        by_src[sc.src].append(sc)

    kept: list[AnalyzedScene] = []
    dropped: list[AnalyzedScene] = []
    for src in srcs_order:
        src_kept: list[AnalyzedScene] = []
        for sc in by_src[src]:
            sc_set = set(sc.main_objects)
            sc_moment = (sc.best_moment or "").strip()
            sc_mid = (sc.start + sc.end) / 2
            is_dup = False
            for i, k in enumerate(src_kept):
                if _jaccard(sc_set, set(k.main_objects)) >= threshold:
                    k_moment = (k.best_moment or "").strip()
                    if sc_moment and k_moment and sc_moment != k_moment:
                        continue
                    k_mid = (k.start + k.end) / 2
                    if abs(sc_mid - k_mid) > time_decay_sec:
                        continue
                    if compute_score(sc) > compute_score(k):
                        dropped.append(k)
                        src_kept[i] = sc
                    else:
                        dropped.append(sc)
                    is_dup = True
                    break
            if not is_dup:
                src_kept.append(sc)
        kept.extend(src_kept)

    if logger:
        logger.info(f"[dedup] {len(analyzed)} → kept {len(kept)}, dropped {len(dropped)} "
                    f"(per-src, 阈值 {threshold}, time_decay={time_decay_sec}s)")
    return kept, dropped


def _natural_key(s: str) -> list[str]:
    """把 ID 切成 [_-] 分段，分段里的数字补零到 8 位作为字符串。"""
    import re
    def pad(piece: str) -> str:
        return re.sub(r'\d+', lambda m: m.group().zfill(8), piece)
    return [pad(p) for p in re.split(r"[_-]", s)]


def _source_id(sc: AnalyzedScene) -> str:
    """从 AnalyzedScene.src（Path）取文件名 stem 作为 source_id。"""
    try:
        return Path(sc.src).stem
    except Exception:
        return str(sc.src)


def _timeline_key(sc: AnalyzedScene, creation_times: dict[str, str]) -> tuple[str, list[str]]:
    """排序键：creation_time 升序，同时间按 id 自然序。"""
    ct = creation_times.get(_source_id(sc), "") or "9999"
    return (ct, _natural_key(sc.id))


def plan(analyzed: list[AnalyzedScene], config: JobConfig,
         beats: Optional[list[float]] = None,
         target_duration: Optional[int] = None,
         cut_duration_range: Optional[tuple[float, float]] = None,
         orchestration_mode: str = "timeline",
         creation_times: Optional[dict[str, str]] = None,
         stages: Optional[list[dict]] = None,
         style_hint: str = "",
         logger: Optional[logging.Logger] = None) -> Storyboard:
    """
    生成 storyboard：
    - orchestration_mode="timeline": 按 creation_time 排序 + per-src 去重 + 算法截断
    - orchestration_mode="llm": 按 stage 序 + 公平时长分配（每 stage 取代表 + 高分填充）

    creation_times: dict[source_id -> creation_time]，时间轴序必须。None 时退回 id 自然序。
    stages: list[{stage, theme, members, representative, ...}]，LLM 模式必须。
    cut_duration_range: (min, max) 来自 yaml style 配置。
    style_hint: 多变体生成时的风格偏移，影响 SCORE_WEIGHTS + role_boost + cut_duration_range。
    """
    target = target_duration or config.target_duration
    ct_map = creation_times or {}
    # style_hint 真的影响选段：调整 cut_duration_range + 让下游 _select_llm_candidates 用新 weights
    effective_cut_range = cut_range_from_style_hint(style_hint, cut_duration_range or (0.8, 1.5))

    def make_item(sc: AnalyzedScene, order: int) -> tuple[StoryboardItem, float]:
        cd = sc.cut_duration
        if effective_cut_range:
            lo, hi = effective_cut_range
            cd = max(lo, min(hi, cd))
        us, ue = compute_cut(sc.start, sc.end, sc.best_frame, cd)
        if ue <= us + 0.3:
            ue = us + 0.5
        dur = ue - us
        return StoryboardItem(
            order=order,
            id=sc.id,
            cut_duration=round(dur, 3),
            subtitle=None,
            use_start=round(us, 3),
            use_end=round(ue, 3),
            reason=sc.best_moment,
        ), dur

    # ============================================================
    # LLM 模式：stage 序 + 代表优先 + 高分填充
    # ============================================================
    if orchestration_mode == "llm" and stages:
        return _plan_llm(analyzed, stages, target, effective_cut_range,
                         make_item, style_hint, logger)

    # ============================================================
    # default 模式：LLM 挑选 + per-src 去重 + 时间序排序
    # ============================================================
    if orchestration_mode == "default" and stages:
        return _plan_default(analyzed, stages, target, ct_map,
                             effective_cut_range, make_item, style_hint, logger)

    # ============================================================
    # timeline 模式（默认）：creation_time 序 + per-src 去重 + 算法截断
    # ============================================================
    return _plan_timeline(analyzed, target, ct_map, effective_cut_range,
                          make_item, logger)


def _plan_timeline(analyzed: list[AnalyzedScene], target: int,
                   ct_map: dict[str, str],
                   cut_duration_range: Optional[tuple[float, float]],
                   make_item, logger: Optional[logging.Logger] = None) -> Storyboard:
    """timeline 模式：creation_time 序 + per-src 去重 + 算法截断。"""
    sorted_scenes = sorted(analyzed, key=lambda a: _timeline_key(a, ct_map))

    kept, dropped = deduplicate(sorted_scenes, threshold=0.7, logger=logger)
    if logger:
        logger.info(f"[plan/timeline] 去重后 {len(kept)} 个场景，dropped {len(dropped)} 个备用")

    def order_strategy(items):
        # 按拍摄时序（creation_time + id 自然序）
        return sorted(items, key=lambda x: _timeline_key(x[0], ct_map))

    items: list[tuple[AnalyzedScene, StoryboardItem, float]] = []
    total = 0.0
    for i, sc in enumerate(kept, 1):
        item, dur = make_item(sc, i)
        items.append((sc, item, dur))
        total += dur

    if total > target * 1.05:
        all_scenes_for_novelty = [x[0] for x in items]
        novelty_map = {
            x[0].id: compute_novelty(x[0], all_scenes_for_novelty)
            for x in items
        }
        sorted_items = sorted(
            items,
            key=lambda x: (
                story_role_priority(x[0]),
                -compute_score(x[0]),
                -novelty_map[x[0].id],
                0 if (x[0].best_moment or "").strip() else 1,
                -x[2],
            ),
        )
        kept_items = []
        running = 0.0
        for sc, item, dur in sorted_items:
            if running >= target * 0.95:
                break
            kept_items.append((sc, item, dur))
            running += dur
        items = order_strategy(kept_items)
        total = sum(x[2] for x in items)
        if logger:
            logger.info(f"[plan/timeline] 截断到 {len(items)} 个瞬时（按拍摄时序），总时长 {total:.2f}s")
    elif total < target * 0.95:
        dropped_sorted = sorted(dropped, key=lambda a: _timeline_key(a, ct_map))
        added = 0
        for sc in dropped_sorted:
            if total >= target * 0.95:
                break
            item, dur = make_item(sc, 0)
            items.append((sc, item, dur))
            total += dur
            added += 1
        items = order_strategy(items)
        if logger:
            logger.info(f"[plan/timeline] 从 dropped 补回 {added} 个（按拍摄时序），总时长 {total:.2f}s")
    else:
        items = order_strategy(items)

    selected = []
    for i, (sc, item, dur) in enumerate(items, 1):
        item.order = i
        selected.append(item)

    board = Storyboard(
        narrative=f"按拍摄时序，{len(selected)} 个瞬时",
        target_duration_sec=target,
        expected_duration_sec=round(total, 2),
        selected=selected,
    )
    if logger:
        logger.info(f"[plan/timeline] storyboard 完成: {len(selected)} 段, 预期 {total:.2f}s (目标 {target}s)")
    return board


def _select_llm_candidates(
    analyzed: list[AnalyzedScene], stages: list[dict], target: int,
    cut_duration_range: Optional[tuple[float, float]],
    make_item, logger: Optional[logging.Logger],
    style_hint: str = "",
) -> tuple[list[tuple[AnalyzedScene, StoryboardItem, float]], list[list[AnalyzedScene]], list[dict], float]:
    """LLM 挑选逻辑（不含排序）：
    - 每 stage members 按 style_hint 加权后的综合分降序
    - representative 必选（i==0）+ 高分填充到 per_stage_budget*1.5
    - 全局截断/补段
    返回 (items, stage_scenes, stage_meta, total)；items 顺序 = stage 序 + stage 内分降序。

    style_hint 经 weights_from_style_hint + role_boost_from_style_hint 解析为权重，
    让多变体生成时不同 variant 真的选出不同段。
    """
    weights = weights_from_style_hint(style_hint)
    role_boost = role_boost_from_style_hint(style_hint)
    if logger and style_hint:
        logger.info(f"[plan/select] style_hint 影响选段: weights={weights} "
                    f"role_boost={{{', '.join(f'{k}:{v}' for k,v in role_boost.items() if v)}}}")

    analyzed_by_id = {a.id: a for a in analyzed}

    stage_scenes: list[list[AnalyzedScene]] = []
    stage_meta: list[dict] = []
    for st in stages:
        members = [analyzed_by_id[mid] for mid in st["members"] if mid in analyzed_by_id]
        if not members:
            continue
        members.sort(key=lambda sc: -compute_score(sc, weights=weights, role_boost=role_boost))
        stage_scenes.append(members)
        stage_meta.append({
            "stage": st.get("stage", 0),
            "theme": st.get("theme", "?"),
            "representative": st.get("representative"),
        })

    if not stage_scenes:
        return [], [], [], 0.0

    n_stages = len(stage_scenes)
    per_stage_budget = target / n_stages

    items: list[tuple[AnalyzedScene, StoryboardItem, float]] = []
    total = 0.0
    for stage_idx, members in enumerate(stage_scenes):
        running_stage = 0.0
        for i, sc in enumerate(members):
            item, dur = make_item(sc, 0)
            if i > 0 and running_stage + dur > per_stage_budget * 1.5:
                break
            items.append((sc, item, dur))
            total += dur
            running_stage += dur

    # 全局截断：超出 target*1.05 时，按 (stage 倒序, stage 内分最低) 砍
    if total > target * 1.05:
        flat_index = []
        cursor = 0
        for stage_idx, members in enumerate(stage_scenes):
            rep_id = stage_meta[stage_idx].get("representative") or (members[0].id if members else None)
            for k in range(len(members)):
                if cursor + k < len(items) and items[cursor + k][0].id == members[k].id:
                    flat_index.append((cursor + k, stage_idx, k, items[cursor + k][0].id == rep_id))
            cursor += len(members)

        def cut_key(entry):
            _, stage_idx, in_idx, rep = entry
            return (0 if rep else 1, -stage_idx, -in_idx)

        order_to_cut = sorted(flat_index, key=cut_key)
        target_total = target * 1.02
        removed = set()
        for entry in order_to_cut:
            if total <= target_total:
                break
            flat_i, _, _, rep = entry
            if rep:
                continue
            total -= items[flat_i][2]
            removed.add(flat_i)
        if removed:
            items = [it for i, it in enumerate(items) if i not in removed]

    # 补回：不足 target*0.95 时，按 stage 序补 stage 内未入选段
    if total < target * 0.95:
        already_ids = {it[0].id for it in items}
        max_round = max((len(m) for m in stage_scenes), default=0)
        for r in range(1, max_round):
            if total >= target * 0.95:
                break
            for stage_idx, members in enumerate(stage_scenes):
                if total >= target * 0.95:
                    break
                if r < len(members):
                    sc = members[r]
                    if sc.id in already_ids:
                        continue
                    item, dur = make_item(sc, 0)
                    items.append((sc, item, dur))
                    total += dur
                    already_ids.add(sc.id)

        def stage_of(sc: AnalyzedScene) -> int:
            for si, members in enumerate(stage_scenes):
                if any(m.id == sc.id for m in members):
                    return si
            return 0

        def in_stage_idx(sc: AnalyzedScene) -> int:
            for members in stage_scenes:
                for k, m in enumerate(members):
                    if m.id == sc.id:
                        return k
            return 0

        items.sort(key=lambda x: (stage_of(x[0]), in_stage_idx(x[0])))

    return items, stage_scenes, stage_meta, total


def _plan_llm(analyzed: list[AnalyzedScene], stages: list[dict], target: int,
              cut_duration_range: Optional[tuple[float, float]],
              make_item, style_hint: str,
              logger: Optional[logging.Logger]) -> Storyboard:
    """LLM 模式：stage 序 + 每 stage 取代表（必选）+ 高分填充（公平时长分配）。"""
    items, stage_scenes, stage_meta, total = _select_llm_candidates(
        analyzed, stages, target, cut_duration_range, make_item, logger,
        style_hint=style_hint)

    if not stage_scenes:
        if logger:
            logger.warning("[plan/llm] 无可用 stage members，退回 timeline 算法")
        return _plan_timeline(analyzed, target, {}, cut_duration_range, make_item, logger)

    n_stages = len(stage_scenes)
    per_stage_budget = target / n_stages

    selected = []
    for i, (sc, item, dur) in enumerate(items, 1):
        item.order = i
        selected.append(item)

    narrative = f"LLM 阶段编排（{n_stages} stages → {len(selected)} 段）"
    board = Storyboard(
        narrative=narrative,
        target_duration_sec=target,
        expected_duration_sec=round(total, 2),
        selected=selected,
    )
    if logger:
        logger.info(f"[plan/llm] storyboard 完成: {len(selected)} 段, 预期 {total:.2f}s (目标 {target}s, "
                    f"{n_stages} stages, budget {per_stage_budget:.2f}s/stage)")
    return board


def _plan_default(analyzed: list[AnalyzedScene], stages: list[dict], target: int,
                  ct_map: dict[str, str],
                  cut_duration_range: Optional[tuple[float, float]],
                  make_item, style_hint: str,
                  logger: Optional[logging.Logger]) -> Storyboard:
    """默认模式：LLM 挑选 -> per-src 去重 -> creation_time + id 自然序排。"""
    items, stage_scenes, _, total = _select_llm_candidates(
        analyzed, stages, target, cut_duration_range, make_item, logger,
        style_hint=style_hint)

    if not stage_scenes:
        if logger:
            logger.warning("[plan/default] 无可用 stage members，退回 timeline 算法")
        return _plan_timeline(analyzed, target, ct_map, cut_duration_range, make_item, logger)

    # 去重：per-src Jaccard（同 timeline）
    scenes_for_dedup = [it[0] for it in items]
    kept, dropped = deduplicate(scenes_for_dedup, threshold=0.7, logger=logger)
    if logger and dropped:
        logger.info(f"[plan/default] LLM 挑选 {len(items)} 段 -> 去重 dropped {len(dropped)} 段")
    kept_ids = {sc.id for sc in kept}
    items = [it for it in items if it[0].id in kept_ids]
    total = sum(it[2] for it in items)

    # 时间序排（creation_time + id 自然序）
    items.sort(key=lambda x: _timeline_key(x[0], ct_map))

    selected = []
    for i, (sc, item, dur) in enumerate(items, 1):
        item.order = i
        selected.append(item)

    narrative = f"默认编排（LLM 挑选 + 去重 + 时间序），{len(selected)} 段"
    board = Storyboard(
        narrative=narrative,
        target_duration_sec=target,
        expected_duration_sec=round(total, 2),
        selected=selected,
    )
    if logger:
        logger.info(f"[plan/default] storyboard 完成: {len(selected)} 段, 预期 {total:.2f}s (目标 {target}s)")
    return board


def save_storyboard(board: Storyboard, job_dir: Path) -> Path:
    out = job_dir / "work" / "storyboard.json"
    out.write_text(
        json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out
