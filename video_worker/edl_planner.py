"""
EDL 规划器：让 GLM 看候选池 + 用户 prompt，生成最终剪辑顺序。

输入：CandidatePool + 用户 prompt + target_duration + style
输出：EDL（按剪辑顺序的片段列表，每段含 use_start/use_end/reason 等）

复用 provider.chat()（纯文本调用，不传图），失败抛 EDLPlanError，由 job.py 捕获后
fallback 到 storyboard。
"""
from __future__ import annotations
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

import yaml

from .validators import (
    CandidatePool, EDL, EDLItem, JobConfig, Style, Storyboard, StoryboardItem,
)
from .providers.base import parse_json_response, ProviderError


class EDLPlanError(Exception):
    """EDL 规划失败"""


STYLE_AVG_CUT = {
    Style.FAST_CUT: 0.8,
    Style.NARRATIVE: 1.5,
    Style.AMBIANCE: 1.6,
}


def _compact_candidate(clip, short_id: str) -> dict:
    """把 CandidateClip 压成精简 dict（喂给 GLM）。
    short_id: 短编号（如 sc_001），避免 GLM 截断长源文件名 id。
    """
    a = clip.analyzed
    return {
        "id": short_id,             # GLM 用短 id；后处理映射回真实 id
        "real_id": a.id,            # 保留映射参考（不传给 GLM）
        "src": Path(a.src).name,    # 只留文件名，省 token
        "start": round(a.start, 2),
        "end": round(a.end, 2),
        "dur": round(a.dur, 2),
        "cut_duration": round(a.cut_duration, 2),
        "best_moment": a.best_moment,
        "main_objects": a.main_objects,
        "highlight_score": a.highlight_score,
        "visual_quality": a.visual_quality,
        "motion_score": a.motion_score,
        "story_role": a.story_role,
        "bad_reason": a.bad_reason,
        "candidate_status": clip.status,
        "candidate_score": clip.score,
    }


def _truncate_candidates(items: list, max_n: int) -> list:
    """超过 max_n 按 candidate_score 降序保留前 N。"""
    if len(items) <= max_n:
        return items
    return sorted(items, key=lambda c: -c.score)[:max_n]


def _build_short_ids(candidates: list) -> dict[str, str]:
    """给候选分配 sc_001 / sc_002 ... 短 id。返回 {short_id: real_id}。"""
    return {f"sc_{i:03d}": c.analyzed.id for i, c in enumerate(candidates, 1)}


def _render_prompt(pool: CandidatePool,
                   config: JobConfig,
                   target_duration: int,
                   tolerance: float,
                   max_candidates: int,
                   prompts_path: Path,
                   short_id_map: dict[str, str],
                   logger: Optional[logging.Logger]) -> str:
    """渲染 edl_planner 模板。short_id_map: {short_id: real_id} 用于喂 GLM 短 id。"""
    cfg = yaml.safe_load(prompts_path.read_text(encoding="utf-8")) or {}
    tpl = cfg.get("templates", {}).get("edl_planner", {}).get("default")
    if not tpl:
        raise EDLPlanError(f"prompt 模板 edl_planner.default 不存在: {prompts_path}")

    # 候选池：keep + maybe（discard 永不进 EDL）
    candidates = list(pool.keep) + list(pool.maybe)
    if not candidates:
        raise EDLPlanError("候选池为空（keep+maybe 都没段）")

    # 截断（控 token）
    candidates = _truncate_candidates(candidates, max_candidates)

    # 重新生成 short_id_map（基于截断后的候选）
    short_id_map.clear()
    for i, c in enumerate(candidates, 1):
        short_id_map[f"sc_{i:03d}"] = c.analyzed.id

    # 生成 compact 时使用 short_id
    compact_list = []
    for short_id, clip in zip(short_id_map.keys(), candidates):
        compact_list.append(_compact_candidate(clip, short_id))

    candidates_json = json.dumps(compact_list, ensure_ascii=False, indent=2)
    user_request = (config.natural_language_request or "").strip() or "（用户未给具体要求，按通用剪辑故事弧规划）"
    avg_cut = STYLE_AVG_CUT.get(config.style, 1.2)

    rendered = tpl.format(
        user_request=user_request,
        target_duration_sec=target_duration,
        style=config.style.value,
        candidates_json=candidates_json,
        duration_min=round(target_duration * (1 - tolerance), 1),
        duration_max=round(target_duration * (1 + tolerance), 1),
    )
    if logger:
        logger.info(
            f"[edl] prompt 渲染完成: {len(rendered)} chars, "
            f"candidates={len(candidates)} (keep={len(pool.keep)} maybe={len(pool.maybe)}), "
            f"style={config.style.value} avg_cut={avg_cut}s"
        )
    return rendered


def _build_analyzed_index(pool: CandidatePool) -> dict[str, object]:
    """从 pool 里建 id -> analyzed 索引（GLM 返回 id 后查边界用）。"""
    idx = {}
    for clip in pool.keep + pool.maybe + pool.discard:
        idx[clip.analyzed.id] = clip.analyzed
    return idx


def _postprocess_items(raw_items: list[dict],
                       pool: CandidatePool,
                       short_id_map: dict[str, str],
                       target_duration: int,
                       tolerance: float,
                       logger: Optional[logging.Logger]) -> list[EDLItem]:
    """后处理 GLM 返回的 items：
    1. short_id → real_id 映射
    2. 过滤未知 id
    3. clamp use_start/use_end 到 analyzed 区间
    4. 丢弃过短段（< 0.3s）
    5. 重新计算 order（连续）
    """
    a_idx = _build_analyzed_index(pool)
    valid_short_ids = set(short_id_map.keys())
    valid_real_ids = set(short_id_map.values())

    cleaned: list[EDLItem] = []
    for raw in raw_items:
        raw_id = str(raw.get("id", "")).strip()
        # 优先按 short_id 匹配；fallback 看是否是 real_id
        if raw_id in valid_short_ids:
            real_id = short_id_map[raw_id]
        elif raw_id in valid_real_ids:
            real_id = raw_id
        else:
            if logger:
                logger.warning(f"[edl] 丢弃未知 id={raw_id!r}（不在候选池）")
            continue
        a = a_idx[real_id]
        try:
            us = float(raw.get("use_start", a.start))
            ue = float(raw.get("use_end", a.end))
        except (TypeError, ValueError):
            if logger:
                logger.warning(f"[edl] {real_id} use_start/use_end 非数值: {raw}")
            continue
        # clamp 到 analyzed 区间
        us = max(a.start, min(a.end, us))
        ue = max(a.start, min(a.end, ue))
        if ue <= us + 0.3:
            # 太短，扩展到 0.5s
            ue = min(a.end, us + 0.5)
            if ue <= us + 0.3:
                if logger:
                    logger.warning(f"[edl] {real_id} 剪辑后过短，跳过")
                continue
        try:
            role = str(raw.get("story_role_assigned", "process")).strip() or "process"
        except Exception:
            role = "process"
        try:
            reason = str(raw.get("reason", ""))[:50]
        except Exception:
            reason = ""
        cleaned.append(EDLItem(
            order=0,  # 重排
            id=real_id,             # 用 real_id（render 时按此找 analyzed）
            use_start=round(us, 3),
            use_end=round(ue, 3),
            cut_duration=round(ue - us, 3),
            story_role_assigned=role,
            reason=reason,
        ))

    # 重新 order
    for i, item in enumerate(cleaned, 1):
        item.order = i

    total = sum(it.cut_duration for it in cleaned)
    duration_min = target_duration * (1 - tolerance)
    duration_max = target_duration * (1 + tolerance)
    if logger:
        logger.info(
            f"[edl] 后处理完成: {len(cleaned)} 段, 总时长 {total:.2f}s "
            f"(目标 [{duration_min:.1f}, {duration_max:.1f}])"
        )
    if total < duration_min or total > duration_max:
        if logger:
            logger.warning(
                f"[edl] 总时长偏离 target ±{int(tolerance*100)}%，但保留 EDL（用户可手动调）"
            )
    return cleaned


@dataclass
class QualityIssue:
    """EDL 质量校验问题。severity=error 触发 fallback storyboard。"""
    severity: Literal["warn", "error"]
    code: str           # 机器可读，如 "consecutive_dup_3"
    message: str        # 人类可读


def _validate_quality(items: list[EDLItem],
                      pool: CandidatePool,
                      target_duration: int,
                      tolerance: float,
                      logger: Optional[logging.Logger]) -> list[QualityIssue]:
    """EDL 质量校验。返回 issues 列表（空 = 完美）。

    检测项：
    - 主体重复：任意相邻 3 段同 main_objects → error；2 连续 → warn
    - 故事弧：前 2 段无 opening/hook → warn；末 2 段无 ending → warn
    - 时长偏离 target ±tolerance → warn
    """
    issues: list[QualityIssue] = []
    a_idx = _build_analyzed_index(pool)

    # 1. 主体重复检测（核心规则）
    obj_sets: list[frozenset] = []
    for it in items:
        a = a_idx.get(it.id)
        objs = getattr(a, "main_objects", None) if a else None
        if objs:
            obj_sets.append(frozenset(objs))
        else:
            obj_sets.append(frozenset())

    def _emit_run(start: int, end: int) -> None:
        """end 是 exclusive 索引（items 索引 0-based）。"""
        run_len = end - start
        if run_len >= 3:
            tag = sorted(obj_sets[start]) if obj_sets[start] else "(unknown)"
            issues.append(QualityIssue(
                severity="error",
                code="consecutive_dup_3",
                message=f"段 {start+1}-{end} 连续 {run_len} 段同主体 {tag}",
            ))
        elif run_len == 2:
            tag = sorted(obj_sets[start]) if obj_sets[start] else "(unknown)"
            issues.append(QualityIssue(
                severity="warn",
                code="consecutive_dup_2",
                message=f"段 {start+1}-{end} 连续 2 段同主体 {tag}",
            ))

    run_start = 0
    for i in range(1, len(obj_sets)):
        # 同主体延续：非空且与前一段相同
        if obj_sets[i] and obj_sets[i] == obj_sets[i-1]:
            continue
        _emit_run(run_start, i)
        run_start = i
    _emit_run(run_start, len(obj_sets))

    # 2. 故事弧校验（WARN 级）
    if items:
        first_roles = {it.story_role_assigned for it in items[:2]}
        if not (first_roles & {"opening", "hook"}):
            issues.append(QualityIssue(
                "warn", "missing_opening",
                f"前 2 段无 opening/hook 角色（实际：{sorted(first_roles)}）",
            ))
        last_roles = {it.story_role_assigned for it in items[-2:]}
        if not (last_roles & {"ending"}):
            issues.append(QualityIssue(
                "warn", "missing_ending",
                f"末 2 段无 ending 角色（实际：{sorted(last_roles)}）",
            ))

    # 3. 时长校验（WARN 级）
    total = sum(it.cut_duration for it in items)
    dmin = target_duration * (1 - tolerance)
    dmax = target_duration * (1 + tolerance)
    if total < dmin or total > dmax:
        issues.append(QualityIssue(
            "warn", "duration_off",
            f"总时长 {total:.2f}s 偏离 [{dmin:.1f}, {dmax:.1f}]",
        ))

    return issues


def _call_with_retry(provider,
                     prompt: str,
                     max_tokens: int,
                     max_attempts: int,
                     logger: Optional[logging.Logger]) -> tuple[Optional[dict], Optional[Exception], str]:
    """对当前 provider.model 做 N 次重试。返回 (data, last_err, last_raw_text)。

    成功条件：parse_json_response 返回 dict 且 data["items"] 非空 list。
    """
    import time as _time
    last_err: Optional[Exception] = None
    raw_text = ""
    data: Optional[dict] = None
    model_name = getattr(provider, "model", "unknown")
    for attempt in range(1, max_attempts + 1):
        try:
            raw_text = provider.chat(prompt, max_tokens=max_tokens)
        except ProviderError as e:
            last_err = e
            if logger:
                logger.warning(f"[edl] [{model_name}] 尝试 {attempt}/{max_attempts} API 失败: {e}")
            if attempt < max_attempts:
                _time.sleep(2 * attempt)
                continue
            break

        if logger:
            logger.info(f"[edl] [{model_name}] 尝试 {attempt}/{max_attempts} 返回 {len(raw_text)} chars")

        data = parse_json_response(raw_text)
        if data and "items" in data and isinstance(data.get("items"), list) and data["items"]:
            break  # 成功
        # 空响应或非法 JSON，重试
        if logger:
            logger.warning(
                f"[edl] [{model_name}] 尝试 {attempt}/{max_attempts} 返回不可用: raw[:200]={raw_text[:200]!r}"
            )
        last_err = EDLPlanError(f"GLM 返回不可用: raw[:200]={raw_text[:200]!r}")
        if attempt < max_attempts:
            _time.sleep(2 * attempt)

    return data, last_err, raw_text


def plan_edl(pool: CandidatePool,
             config: JobConfig,
             provider,
             target_duration: Optional[int] = None,
             max_candidates: int = 40,
             tolerance: float = 0.2,
             prompts_path: Optional[Path] = None,
             fallback_models: Optional[list[str]] = None,
             primary_model: Optional[str] = None,
             logger: Optional[logging.Logger] = None) -> EDL:
    """
    调 GLM 规划 EDL。失败抛 EDLPlanError。

    provider: 必须支持 chat()（glm 系列）
    fallback_models: 主模型全部失败时按序尝试的后备模型名（如 ["glm-4-plus"]）。
                     临时切换 provider.model，调用结束 finally 恢复原值。
    primary_model: EDL 规划主模型覆盖（不影响 provider.model 用于视觉分析）。
                   用于让视觉用 glm-4.6v、EDL 用 glm-5.2 这种分模型场景。
                   None 时用 provider.model。finally 仍恢复原 provider.model。
    """
    if not hasattr(provider, "chat"):
        raise EDLPlanError(f"provider {provider.name} 不支持 chat，无法规划 EDL")

    target = target_duration or config.target_duration

    # 加载 edl_planner 模板（用 default.yaml 配的或 bundled）
    if prompts_path is None:
        from .paths import bundle_root
        prompts_path = bundle_root() / "configs" / "prompts.yaml"
    if not prompts_path.exists():
        raise EDLPlanError(f"prompts.yaml 不存在: {prompts_path}")

    # 渲染 prompt（同时填充 short_id_map）
    short_id_map: dict[str, str] = {}
    prompt = _render_prompt(pool, config, target, tolerance,
                            max_candidates, prompts_path, short_id_map, logger)

    # 调 provider.chat：主模型 N 次重试，全失败则切换 fallback_models 重试
    max_attempts = 3
    original_model = getattr(provider, "model", None)
    primary = primary_model or original_model
    models_to_try = [primary] + list(fallback_models or [])

    data: Optional[dict] = None
    last_err: Optional[Exception] = None
    raw_text = ""
    used_model = original_model

    try:
        for model_idx, model_name in enumerate(models_to_try):
            if model_name is None:
                continue
            provider.model = model_name
            if model_idx > 0 and logger:
                logger.warning(f"[edl] 主模型全部失败，切换到 fallback 模型: {model_name}")
            data, last_err, raw_text = _call_with_retry(
                provider, prompt, max_tokens=4096,
                max_attempts=max_attempts, logger=logger,
            )
            if data and "items" in data and isinstance(data.get("items"), list) and data["items"]:
                used_model = model_name
                break
            if logger:
                logger.warning(f"[edl] 模型 {model_name} 全部重试失败")
    finally:
        # 必须恢复原值，避免污染 provider 后续 vision 调用
        if original_model is not None:
            provider.model = original_model

    if not data or "items" not in data:
        if last_err:
            raise EDLPlanError(
                f"所有模型（{models_to_try}）各 {max_attempts} 次都失败: {last_err}"
            ) from last_err
        raise EDLPlanError(
            f"所有模型返回均不可用: raw[:300]={raw_text[:300]!r}"
        )
    raw_items = data.get("items") or []
    if not isinstance(raw_items, list) or not raw_items:
        raise EDLPlanError(f"GLM 返回 items 为空或非列表: {data!r}")

    # 后处理（用 short_id_map 反查 real_id）
    items = _postprocess_items(raw_items, pool, short_id_map,
                                target, tolerance, logger)
    if not items:
        raise EDLPlanError("后处理后 EDL items 为空")

    # 质量校验（3+ 连续同主体 → error 抛出 → job.py fallback storyboard）
    issues = _validate_quality(items, pool, target, tolerance, logger)
    errors = [i for i in issues if i.severity == "error"]
    if logger:
        for iss in issues:
            if iss.severity == "error":
                logger.warning(f"[edl] quality ERROR [{iss.code}] {iss.message}")
            else:
                logger.info(f"[edl] quality warn [{iss.code}] {iss.message}")
    if errors:
        raise EDLPlanError(
            f"EDL 质量校验失败 ({len(errors)} errors): " +
            "; ".join(e.message for e in errors)
        )

    narrative = str(data.get("narrative", "")).strip() or "(无 narrative)"
    prompt_hash = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]
    total = round(sum(it.cut_duration for it in items), 2)

    return EDL(
        job_id=pool.job_id,
        narrative=narrative[:200],  # 截断保险
        target_duration_sec=target,
        expected_duration_sec=total,
        selected=items,
        model=used_model or "unknown",
        prompt_hash=prompt_hash,
    )


def edl_to_storyboard(edl: EDL) -> Storyboard:
    """把 EDL 转成 Storyboard，复用 render.render()。"""
    return Storyboard(
        narrative=edl.narrative,
        target_duration_sec=edl.target_duration_sec,
        expected_duration_sec=edl.expected_duration_sec,
        selected=[
            StoryboardItem(
                order=it.order,
                id=it.id,
                cut_duration=it.cut_duration,
                subtitle=it.subtitle,
                use_start=it.use_start,
                use_end=it.use_end,
                reason=it.reason,
            ) for it in edl.selected
        ],
    )


def save_edl(edl: EDL, job_dir: Path) -> Path:
    """落盘 work/edl.json"""
    out = job_dir / "work" / "edl.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(edl.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out
