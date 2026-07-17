"""
tandao2 混合方案：时间轴 + VLM + LLM（fresh 全跑）

流程：
1. preprocess + 场景切分 + 抽帧（无模型，deterministic）
2. ★ VLM 视觉分析（fresh，42 次调用）
3. 每源选 top-1 + 按 creation_time 时间轴排序（本地）
4. VLM-aware 去重：main_objects Jaccard ≥ 0.5 AND action_type 同 → 同簇留最高分
5. ★ LLM 时长分配（fresh，1 次调用，输入按时间序的候选段）
6. 渲染

用法：
    python scripts/tandao2_hybrid_test.py --provider glm
    python scripts/tandao2_hybrid_test.py --provider doubao
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from video_worker import (
    media_scan, preprocess, scene_detect, frame_extract,
    vision_analyze, render, config,
)
from video_worker.validators import (
    AnalyzedScene, JobConfig, Storyboard, StoryboardItem, Style, Provider,
)
from video_worker.paths import resolve_ffmpeg
from video_worker.providers.base import parse_json_response

# Phase 15：read_creation_time + llm_timeline_dedup 迁移到 video_worker/timeline_dedup.py
# 这里 re-export 保持 curate_service 等下游兼容
from video_worker.timeline_dedup import (
    read_creation_time as _read_creation_time_impl,
    cluster_by_timeline,
)


def read_creation_time(ffmpeg: Path, video_path: Path) -> str:
    """兼容包装：转发到 video_worker.timeline_dedup.read_creation_time。"""
    return _read_creation_time_impl(ffmpeg, video_path)


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def _get_sample_frames(scene_id: str, frames_seq_dir: Path, max_frames: int = 3) -> list[Path]:
    """采样场景的代表帧（首/中/尾最多 3 张）。文件命名：<scene_id>_f*.jpg"""
    frames = sorted(frames_seq_dir.glob(f"{scene_id}_f*.jpg"))
    if not frames:
        return []
    if len(frames) <= max_frames:
        return frames
    n = len(frames)
    # 首、中、尾
    indices = [0, n // 2, n - 1]
    return [frames[i] for i in indices[:max_frames]]


def _compute_phash(image_path: Path, hash_size: int = 8):
    try:
        import imagehash
        from PIL import Image
        return imagehash.phash(Image.open(image_path), hash_size=hash_size)
    except Exception:
        return None


def _min_phash_distance(hashes_a: list, hashes_b: list) -> int | None:
    """两段的所有帧两两比较，取最小 Hamming 距离。"""
    if not hashes_a or not hashes_b:
        return None
    return min(a - b for a in hashes_a for b in hashes_b)


def vlm_aware_dedup(scenes: list,
                    jaccard_threshold: float = 0.5,
                    frames_seq_dir: Path | None = None,
                    phash_threshold: int | None = None,
                    phash_hash_size: int = 8) -> tuple[list, list]:
    """聚类去重。两段判为同簇的条件（满足任一即合并）：

    A. VLM 标签匹配：main_objects Jaccard ≥ threshold AND action_type 同
    B. 像素匹配：所有采样帧两两 pHash 最小 Hamming 距离 < phash_threshold

    hash_size=8（64-bit）+ 多帧采样比 hash_size=16 单帧更能抓"同场景不同时刻"的重复。
    典型参数：hash_size=8, phash_threshold=10（约 15% 位差）。

    同簇按 highlight_score 保留最高。
    scenes 已按 creation_time 升序。返回 (survivors, dropped_info)。
    """
    # 预算每段的 pHash 列表（首/中/尾）
    phashes: dict[int, list] = {}
    if frames_seq_dir and phash_threshold:
        for idx, sc in enumerate(scenes):
            frames = _get_sample_frames(sc["id"], frames_seq_dir, max_frames=3)
            hs = [h for h in (_compute_phash(f, hash_size=phash_hash_size) for f in frames) if h is not None]
            if hs:
                phashes[idx] = hs

    clusters: list[list] = []  # 每簇: [(idx, scene)]
    for idx, sc in enumerate(scenes):
        placed = False
        for cluster in clusters:
            rep_idx, rep = cluster[0]
            # 条件 A：VLM 标签
            same_action = (sc.get("action_type") or "") == (rep.get("action_type") or "")
            same_objs = jaccard(
                set(sc.get("main_objects") or []),
                set(rep.get("main_objects") or []),
            ) >= jaccard_threshold
            vlm_match = same_action and same_objs

            # 条件 B：pHash 像素相似（任一帧匹配即合并）
            phash_match = False
            if phash_threshold and idx in phashes and rep_idx in phashes:
                distance = _min_phash_distance(phashes[idx], phashes[rep_idx])
                if distance is not None and distance < phash_threshold:
                    phash_match = True

            if vlm_match or phash_match:
                cluster.append((idx, sc))
                placed = True
                break
        if not placed:
            clusters.append([(idx, sc)])

    survivors = []
    dropped = []
    for cluster in clusters:
        sorted_c = sorted(
            cluster,
            key=lambda x: x[1].get("highlight_score", 0)
                       + x[1].get("visual_quality", 0) * 0.3,
            reverse=True,
        )
        survivors.append(sorted_c[0])
        for idx, sc in sorted_c[1:]:
            dropped.append({
                "id": sc["id"],
                "kept": sorted_c[0][1]["id"],
                "highlight": sc.get("highlight_score"),
                "kept_highlight": sorted_c[0][1].get("highlight_score"),
            })
    survivors.sort(key=lambda x: x[0])  # 按 idx 还原时间序
    return [s[1] for s in survivors], dropped


def llm_semantic_dedup(scenes: list, provider, llm_model: str,
                       logger=None) -> tuple[list, list]:
    """LLM 语义去重：让 LLM 把"画面内容相似"的段归为同簇，每簇留最高分。

    比 vlm_aware_dedup 强的地方：能识别"水果盘+杏" / "水果盘+柠檬" / "水果盘+水蜜桃"
    都是"水果盘展示"这种语义同簇，不受字面 main_objects 差异影响。
    """
    import json as _json
    from video_worker.providers.base import parse_json_response

    if not scenes:
        return [], []

    segs = []
    for s in scenes:
        segs.append({
            "id": s["id"],
            "main_objects": s.get("main_objects") or [],
            "action_type": s.get("action_type") or "",
            "highlight_score": s.get("highlight_score", 5),
        })

    prompt = f"""你是专业视频剪辑师。下面是 {len(segs)} 个候选段，每个有 main_objects（画面里的主体）和 action_type（动作类型）。
请把【画面内容相似】的段分为同一组（同组 = 视觉上看起来在拍同一件事，即使具体物体略不同）。

**判断相似的标准**：
- 同一种动作 + 同一类主体（即使具体物体不同）= 相似
  - 例：[水果盘, 黄色水果] / [水果盘, 杏] / [水果盘, 红色水果] → 都是"水果盘展示" → 同组
  - 例：[白盘, 杏子] / [白盘, 樱桃] / [白盘, 小刀] → 都是"白盘装饰" → 同组
  - 例：[酒瓶, 玻璃杯, 倒酒] / [摇酒杯, 玻璃杯, 倒酒] → 都是"倒酒入杯" → 同组
- 不同动作 或 明显不同的主体 = 不相似
  - 例：[水果盘, preparation] vs [酒瓶, pouring] → 不同组
  - 例：[白盘, decoration] vs [酒瓶, pouring] → 不同组

**候选段**：
{_json.dumps(segs, ensure_ascii=False, indent=2)}

**输出 JSON**（严格）：
{{
  "clusters": [
    {{"theme": "<短主题，<10字>", "members": ["<id1>", "<id2>", ...]}},
    ...
  ]
}}

要求：
1. 每个 id 必须且只能出现在一个 cluster 的 members 里
2. 单元素 cluster 允许（独特画面）
3. theme 用具体描述（如"水果盘展示"/"白盘装饰"/"倒酒入杯"/"瓶身特写"）
4. 不要编造 id，只能用候选段里出现的
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[llm-dedup] 调用 {llm_model} 给 {len(segs)} 段聚类...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "clusters" not in data:
            raise RuntimeError(f"LLM dedup 返回无效: raw[:300]={raw[:300]!r}")
    finally:
        provider.model = original_model

    # 构建 id → cluster_id 映射
    id_to_cluster: dict[str, int] = {}
    cluster_themes: dict[int, str] = {}
    for i, c in enumerate(data["clusters"]):
        theme = c.get("theme", f"cluster_{i}")
        cluster_themes[i] = theme
        for mid in c.get("members", []):
            id_to_cluster[mid] = i

    # 按 cluster 分桶
    cluster_members: dict[int, list] = defaultdict(list)
    for s in scenes:
        cid = id_to_cluster.get(s["id"])
        if cid is None:
            cid = -1  # LLM 漏掉了，单独成簇
            cluster_themes[cid] = "(ungrouped)"
        cluster_members[cid].append(s)

    def composite(s):
        return (s.get("highlight_score", 0) * 0.5
                + s.get("visual_quality", 0) * 0.3
                + s.get("motion_score", 0) * 0.2)

    survivors = []
    dropped = []
    for cid, members in cluster_members.items():
        members.sort(key=composite, reverse=True)
        survivors.append(members[0])
        for s in members[1:]:
            dropped.append({
                "id": s["id"],
                "kept": members[0]["id"],
                "theme": cluster_themes.get(cid, "?"),
                "score": composite(s),
                "kept_score": composite(members[0]),
            })

    if logger:
        for cid, members in cluster_members.items():
            theme = cluster_themes.get(cid, "?")
            if len(members) > 1:
                ids = [m["id"] for m in members]
                kept = max(members, key=composite)["id"]
                logger.info(f"  [cluster] {theme}（{len(members)}段）: "
                            f"{ids} → 保留 {kept}")

    survivors.sort(key=lambda s: s.get("creation_time", "9999"))
    return survivors, dropped


def llm_timeline_dedup(scenes: list, provider, llm_model: str,
                       logger=None, return_stages: bool = False):
    """时间轴感知的 LLM 去重：只能合并时间上**相邻或连续**的段为同簇。

    比 llm_semantic_dedup 多一层约束：保留故事弧。
    语义相同的段如果时间不连续（中间隔着不同语义），算两个独立"阶段"。

    输入 scenes 必须已按 creation_time 升序排好。

    返回 (survivors, dropped)；当 return_stages=True 时多返回一个 stages 列表：
      [{"stage": 1, "theme": "...", "members": [id, ...], "representative": id, "score_range": [min, max]}]
    """
    import json as _json
    from video_worker.providers.base import parse_json_response

    if not scenes:
        if return_stages:
            return [], [], []
        return [], []

    # 输入按时间序，给 LLM 带 order
    segs = []
    for i, s in enumerate(scenes, 1):
        segs.append({
            "order": i,
            "id": s["id"],
            "main_objects": s.get("main_objects") or [],
            "action_type": s.get("action_type") or "",
            "highlight_score": s.get("highlight_score", 5),
        })

    target_stages = max(8, min(20, len(segs) // 10))
    prompt = f"""你是专业视频剪辑师。下面是按**拍摄时间顺序**排列的 {len(segs)} 个候选段。
请把它们分成"故事阶段"——一个阶段是时间上**连续**、属于同一动作流程或场景的片段集合。

**目标阶段数：约 {target_stages} 个**（不要过碎）。

**关键规则**（按重要性排序）：
1. **只能合并列表中相邻或连续的段**。一个 stage 的 order 必须是连续整数（[3,4,5] 可以；[3,5,7] 不行）。
2. **动作流程一致就合并**：相邻段的 action_type 相同（都是"倒酒"/"摇酒"/"切水果"/"摇镜头特写"等），即使 main_objects 略有差异，**必须合并为同一阶段**。
3. **跨语义才拆分**：只有中间明确隔了完全不同的动作（如"调酒过程"中插入"成品展示"），才必须分成两个阶段。
   - 例：order=[1..7] action=[倒酒, 倒酒, 倒酒, 水果, 水果, 倒酒, 倒酒]
   - 正确：[1,2,3]=开场倒酒 / [4,5]=水果准备 / [6,7]=收尾倒酒
4. **VLM 切片有偏差**：相邻段即使 main_objects 不完全一致（如"果盘+杏"vs"果盘+柠檬"），只要描述同一动作流程的不同瞬间，**合并**。
5. 每个阶段理想 5-15 段；少于 3 段的阶段只允许出现在真正独特的画面（瓶身特写/最终成品）。
6. theme 用具体描述（如"开场倒酒"/"水果切配"/"瓶身特写"），不超过 10 字。

**候选段（已按时间序，order 1=最早）**：
{_json.dumps(segs, ensure_ascii=False, indent=2)}

**输出 JSON**（严格）：
{{
  "stages": [
    {{"theme": "<短主题>", "members": [<order1>, <order2>, ...]}},
    ...
  ]
}}

要求：
1. stages 顺序必须按时间排（第一个 stage 包含 order 1）
2. 每个 order 必须且只能出现在一个 stage 里
3. 每个 stage 的 members 必须是连续整数
4. 不要编造 order
5. **总阶段数目标 {target_stages} 个左右，不要超过 {target_stages * 2} 个**
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[llm-timeline-dedup] 调用 {llm_model} 给 {len(segs)} 段分阶段...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "stages" not in data:
            raise RuntimeError(f"LLM timeline dedup 返回无效: raw[:300]={raw[:300]!r}")
    finally:
        provider.model = original_model

    # 构建 order → stage_id 映射 + 校验连续性
    order_to_stage: dict[int, int] = {}
    stage_themes: dict[int, str] = {}
    for i, st in enumerate(data["stages"]):
        theme = st.get("theme", f"stage_{i+1}")
        members = st.get("members", [])
        stage_themes[i] = theme
        # 校验 members 连续
        if members:
            sorted_m = sorted(members)
            for j in range(1, len(sorted_m)):
                if sorted_m[j] != sorted_m[j-1] + 1:
                    if logger:
                        logger.warning(f"  [timeline] stage {i+1} '{theme}' members 不连续: {sorted_m}")
                    break
        for m in members:
            order_to_stage[m] = i

    # 按 stage 分桶（保留时间序）
    stage_members: dict[int, list] = defaultdict(list)
    for i, s in enumerate(scenes, 1):
        sid = order_to_stage.get(i)
        if sid is None:
            sid = -1
            stage_themes[sid] = "(ungrouped)"
        stage_members[sid].append(s)

    def composite(s):
        return (s.get("highlight_score", 0) * 0.5
                + s.get("visual_quality", 0) * 0.3
                + s.get("motion_score", 0) * 0.2)

    survivors = []
    dropped = []
    for sid, members in stage_members.items():
        members_sorted = sorted(members, key=composite, reverse=True)
        survivors.append(members_sorted[0])
        for s in members_sorted[1:]:
            dropped.append({
                "id": s["id"],
                "kept": members_sorted[0]["id"],
                "theme": stage_themes.get(sid, "?"),
            })

    # survivors 按 stage 时间序（即按 stage_id 升序，每个 stage 内的代表）
    # 因为输入已按时间序，stage_id 顺序对应时间序
    survivors.sort(key=lambda s: s.get("creation_time", "9999"))

    if logger:
        for sid in sorted(stage_themes.keys()):
            members = stage_members[sid]
            theme = stage_themes[sid]
            ids = [m["id"] for m in members]
            kept = max(members, key=composite)["id"]
            tag = f"（{len(members)}段→保留 {kept}）" if len(members) > 1 else f"（独立段）"
            logger.info(f"  [stage {sid+1}] {theme}{tag}: {ids}")

    if return_stages:
        # 构造 stages 结构（按 stage_id 时间序）
        stages_out = []
        for sid in sorted(stage_members.keys()):
            members = stage_members[sid]
            scores = [m.get("highlight_score", 0) for m in members]
            rep = max(members, key=composite)
            stages_out.append({
                "stage": sid + 1,  # 1-indexed
                "theme": stage_themes.get(sid, "?"),
                "members": [m["id"] for m in members],
                "representative": rep["id"],
                "score_range": [min(scores), max(scores)] if scores else [0, 0],
                "size": len(members),
            })
        return survivors, dropped, stages_out

    return survivors, dropped


def _encode_thumbnail_middle(scene_id: str, frames_seq_dir,
                             max_size: tuple = (360, 640), quality: int = 80) -> str | None:
    """找场景的中间帧，缩到 max_size 内，base64 编码 JPEG 返回 data URI。"""
    import base64 as _b64
    import io as _io
    try:
        from PIL import Image
    except ImportError:
        return None

    frames = sorted(frames_seq_dir.glob(f"{scene_id}_f*.jpg"))
    if not frames:
        return None
    frame = frames[len(frames) // 2]
    try:
        img = Image.open(frame)
        img.thumbnail(max_size, Image.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        b64 = _b64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def generate_html_report(scenes: list, stages: list, job_dir, target: float,
                         logger=None) -> "Path":
    """生成自包含 HTML 报告，每 stage 一个 section。

    scenes: 全部场景 dict 列表（含 main_objects / action_type / scores）
    stages: llm_timeline_dedup(return_stages=True) 返回的 stages
    job_dir: job 根目录（找 work/frames_seq/）
    target: 目标时长（显示在 header）
    """
    scene_lookup = {s["id"]: s for s in scenes}
    frames_seq_dir = job_dir / "work" / "frames_seq"

    # 预算所有用到的 scene id 的缩略图
    needed_ids = set()
    for st in stages:
        for mid in st["members"]:
            needed_ids.add(mid)

    if logger:
        logger.info(f"[report] 编码 {len(needed_ids)} 张缩略图...")
    thumb_cache: dict[str, str | None] = {}
    for sid in needed_ids:
        thumb_cache[sid] = _encode_thumbnail_middle(sid, frames_seq_dir)

    # 渲染每 stage 的 HTML 卡片
    stage_blocks = []
    for st in stages:
        rep_id = st["representative"]
        cards_html = []
        # representative 排第一
        members_ordered = [rep_id] + [m for m in st["members"] if m != rep_id]
        for mid in members_ordered:
            s = scene_lookup.get(mid, {})
            thumb = thumb_cache.get(mid)
            img_html = (f'<img src="{thumb}" alt="{mid}">'
                        if thumb else
                        f'<div class="no-img">无缩略图</div>')
            objs = "/".join(s.get("main_objects") or [])[:30] or "—"
            is_rep = (mid == rep_id)
            card_class = "scene-card representative" if is_rep else "scene-card"
            star = '<span class="star">★ auto</span>' if is_rep else ""
            score = s.get("highlight_score", "?")
            act = s.get("action_type", "?")
            dur = s.get("end", 0) - s.get("start", 0)
            cards_html.append(f"""
            <div class="{card_class}">
              {img_html}
              <div class="meta">
                <div class="id">{mid} {star}</div>
                <div class="row">score=<b>{score}</b> act={act} dur={dur:.1f}s</div>
                <div class="objs">{objs}</div>
              </div>
            </div>""")

        score_range = st.get("score_range", [0, 0])
        stage_blocks.append(f"""
        <section class="stage">
          <h2>Stage {st['stage']}: {st['theme']}
            <span class="badge">{st['size']} 段 · score {score_range[0]}-{score_range[1]}</span>
          </h2>
          <div class="cards">{''.join(cards_html)}</div>
        </section>""")

    total_scenes = sum(st["size"] for st in stages)
    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Curation Report - {job_dir.name}</title>
<style>
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         background: #1a1a1a; color: #eee; margin: 0; padding: 20px; }}
  h1 {{ color: #fff; border-bottom: 1px solid #444; padding-bottom: 10px; }}
  .summary {{ background: #222; padding: 12px 16px; border-radius: 6px; margin-bottom: 24px;
              display: flex; gap: 24px; flex-wrap: wrap; }}
  .summary div {{ font-size: 14px; }}
  .summary b {{ color: #ffcc00; font-size: 18px; }}
  section.stage {{ margin-bottom: 32px; background: #222; padding: 16px; border-radius: 8px; }}
  h2 {{ color: #fff; font-size: 18px; margin-top: 0; }}
  .badge {{ background: #444; padding: 2px 8px; border-radius: 4px; font-size: 12px;
            color: #ccc; margin-left: 8px; font-weight: normal; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px; }}
  .scene-card {{ background: #2c2c2c; border-radius: 6px; overflow: hidden;
                 border: 2px solid transparent; }}
  .scene-card.representative {{ border-color: #ffcc00; }}
  .scene-card img {{ width: 100%; display: block; aspect-ratio: 9/16; object-fit: cover; }}
  .no-img {{ aspect-ratio: 9/16; display: flex; align-items: center; justify-content: center;
             color: #666; background: #1a1a1a; }}
  .meta {{ padding: 8px; font-size: 12px; }}
  .id {{ color: #fff; font-weight: bold; margin-bottom: 4px; }}
  .row {{ color: #aaa; margin-bottom: 2px; }}
  .objs {{ color: #888; font-size: 11px; }}
  .star {{ color: #ffcc00; font-weight: normal; font-size: 11px; }}
  .help {{ background: #2a2a1a; border-left: 3px solid #ffcc00; padding: 8px 12px;
           margin-bottom: 16px; font-size: 13px; color: #ccc; }}
</style></head>
<body>
<h1>Curation Report</h1>
<div class="summary">
  <div>目标时长 <b>{target:.0f}s</b></div>
  <div>故事阶段 <b>{len(stages)}</b></div>
  <div>候选段总数 <b>{total_scenes}</b></div>
  <div>缩略图 <b>{sum(1 for v in thumb_cache.values() if v)}/{len(needed_ids)}</b></div>
</div>
<div class="help">
  ★ 标记 = 该 stage 内 composite_score 最高的段（默认 auto-pick）。<br>
  把鼠标移到卡片上看细节，记下你想保留 / 替换 / 删除的 scene_id。
</div>
{''.join(stage_blocks)}
</body></html>
"""
    out = job_dir / "work" / "curate_report.html"
    out.write_text(html, encoding="utf-8")
    if logger:
        logger.info(f"[report] 写入 {out} ({out.stat().st_size/1024:.0f} KB)")
    return out


def curate_with_brief(scenes: list, stages: list, brief: str, target: float,
                      provider, llm_model: str, logger=None,
                      min_dur: float = 0.6, max_dur: float = 4.0) -> list[dict]:
    """LLM 拿 brief + stages → selections [{id, duration, reason}]，顺序 = 显示顺序。

    单次调用同时挑段 + 分配时长，归一化保证 sum == target。
    """
    import json as _json
    from video_worker.providers.base import parse_json_response

    scene_lookup = {s["id"]: s for s in scenes}

    # 构造 stage 索引（含所有候选段供 LLM 选）
    stage_index = []
    for st in stages:
        members_info = []
        for mid in st["members"]:
            s = scene_lookup.get(mid, {})
            members_info.append({
                "id": mid,
                "score": s.get("highlight_score", 5),
                "main_objects": s.get("main_objects") or [],
                "action_type": s.get("action_type") or "",
                "duration_range_s": [round(s.get("start", 0), 2), round(s.get("end", 0), 2)],
            })
        stage_index.append({
            "stage": st["stage"],
            "theme": st["theme"],
            "members": members_info,
        })

    prompt = f"""你是专业视频剪辑师，给一段素材做最终剪辑决策。

**用户 brief（创作意图）**：
{brief}

**目标时长**：{target} 秒（严格 ±5%）

**可用场景池**（按故事阶段组织，已按拍摄时间序；每段给出 main_objects / action_type / score / 可用时长区间）：
{_json.dumps(stage_index, ensure_ascii=False, indent=2)}

**任务**：
1. 按 brief 决定哪些 stage 入选；每个 stage 可选 1 段代表（也可不选 / 选不同段）。
2. 决定显示顺序（**不必按 stage 顺序**，可重排以满足 brief 的开场 / 中段 / 收尾等要求）。
3. 给每段分配时长，总时长严格 = {target}。
4. 单段 [{min_dur}, {max_dur}] 秒；时长不能超出该段的 duration_range_s。
5. **充分尊重 brief**；brief 没说到的，按你的专业判断挑。
6. 段数建议 10-25 段（按 target_duration 调整）。

**输出 JSON**（严格）：
{{
  "selections": [
    {{"id": "<scene_id>", "duration": <float>, "reason": "<15 字内说明>"}},
    ...
  ],
  "total": <应当 = {target}>,
  "narrative": "<一句话描述最终叙事弧>"
}}
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[curate] 调用 {llm_model}（brief 长度 {len(brief)} 字）...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "selections" not in data:
            raise RuntimeError(f"curate_with_brief 返回无效: raw[:300]={raw[:300]!r}")
    finally:
        provider.model = original_model

    # 过滤掉不存在的 id（LLM 偶尔会编造）
    selections = []
    for sel in data["selections"]:
        sid = sel.get("id")
        if sid not in scene_lookup:
            if logger:
                logger.warning(f"[curate] 丢弃不存在的 id: {sid}")
            continue
        s = scene_lookup[sid]
        a_dur = s["end"] - s["start"]
        d = float(sel.get("duration", min(max_dur, a_dur)))
        d = max(min_dur, min(max_dur, min(d, a_dur)))
        selections.append({
            "id": sid,
            "duration": d,
            "reason": sel.get("reason", ""),
            "scene": s,
        })

    # 归一化到 target（复用 allocate_duration_llm 的尾巴逻辑）
    total = sum(s["duration"] for s in selections)
    if total > 0 and abs(total - target) > 0.5:
        scale = target / total
        for s in selections:
            s["duration"] = round(s["duration"] * scale, 3)
        diff = target - sum(s["duration"] for s in selections)
        if abs(diff) > 0.01 and selections:
            selections[-1]["duration"] = round(selections[-1]["duration"] + diff, 3)

    if logger:
        logger.info(f"[curate] 选 {len(selections)} 段, 总时长 {sum(s['duration'] for s in selections):.2f}s")
        logger.info(f"[curate] narrative: {data.get('narrative', '?')}")
        for i, s in enumerate(selections, 1):
            logger.info(f"  {i:>2}. {s['id']:<12} {s['duration']:.2f}s  {s['reason']}")

    return selections


def curate_with_selection(scenes: list, selection_scene_ids: list[str],
                          target: float, provider, llm_model: str,
                          logger=None, brief: str = "",
                          min_dur: float = 0.6, max_dur: float = 4.0) -> list[dict]:
    """LLM 在用户勾选集合内做最终剪辑决策（硬约束模式）。

    与 curate_with_brief 的差别：
    - LLM 只看到勾选的 scene，不知道有其他段
    - 必须、且只能使用勾选集合内的段（不能新增、不能完全不用）
    - 如果勾选总可用时长 > target，LLM 在勾选内挑 subset
    - 如果勾选总可用时长 < target，LLM 把每段拉到 max_dur 上限，仍不够则成片就短

    selection_scene_ids: 用户勾选的 scene id 列表
    brief: 可选自然语言意图（空字符串则纯按勾选 + LLM 审美决策）

    返回 selections: [{"id", "duration", "reason", "scene"}] 顺序 = 显示顺序
    """
    import json as _json
    from video_worker.providers.base import parse_json_response

    selected_set = set(selection_scene_ids)
    selected_scenes = [s for s in scenes if s["id"] in selected_set]
    if not selected_scenes:
        if logger:
            logger.warning("[curate-sel] 勾选集合为空")
        return []

    # 给 LLM 看的"完整素材池" = 勾选集合（不暴露未勾选段）
    # 顺序尊重 selection_scene_ids（用户拖拽 stage 后的顺序）；找不到的回退到 selected_scenes 顺序
    selected_by_id = {s["id"]: s for s in selected_scenes}
    ordered_ids = [sid for sid in selection_scene_ids if sid in selected_by_id]
    # 兜底：selected_scenes 里有但 selection_scene_ids 漏掉的（理论上不会发生）
    for s in selected_scenes:
        if s["id"] not in ordered_ids:
            ordered_ids.append(s["id"])

    pool_info = []
    total_avail = 0.0
    for sid in ordered_ids:
        s = selected_by_id[sid]
        a_start = s.get("start", 0)
        a_end = s.get("end", 0)
        a_dur = a_end - a_start
        total_avail += a_dur
        pool_info.append({
            "id": s["id"],
            "main_objects": s.get("main_objects") or [],
            "action_type": s.get("action_type") or "",
            "highlight_score": s.get("highlight_score", 5),
            "creation_time": s.get("creation_time", ""),
            "duration_range_s": [round(a_start, 2), round(a_end, 2)],
            "available_duration_s": round(a_dur, 2),
        })

    brief_block = f"**用户 brief（创作意图，可选）**：\n{brief}" if brief.strip() else "(用户未提供 brief，按你的专业审美决策)"

    prompt = f"""你是专业视频剪辑师。下面是用户**已勾选**的视频片段池，请基于此做最终剪辑决策。

{brief_block}

**目标时长**：{target} 秒（严格 ±5%）

**用户勾选的片段池**（共 {len(pool_info)} 段，总可用时长 {total_avail:.1f}s；已按用户拖拽 stage 后的顺序）：
{_json.dumps(pool_info, ensure_ascii=False, indent=2)}

**硬约束**：
1. **必须且只能使用上述片段池中的段**——不能新增、不能完全不用。
2. 如果总可用时长（{total_avail:.1f}s）> target（{target}s），你需要在池内挑 subset（不是每段都用）。
3. 如果总可用时长 < target，每段时长尽量拉到该段 available_duration_s 上限（不超过 {max_dur}s）；仍不够则成片就短，不要硬塞。
4. 单段时长 [{min_dur}, {max_dur}] 秒，且不能超过该段的 available_duration_s。
5. **不要重排顺序**——按输入池中的顺序（用户拖拽 stage 后的顺序）输出 selections。用户的 stage 顺序就是叙事顺序。
6. 总时长严格 = {target}（受约束 3 影响时，输出实际总时长）。

**输出 JSON**（严格）：
{{
  "selections": [
    {{"id": "<scene_id>", "duration": <float>, "reason": "<15 字内说明>"}},
    ...
  ],
  "total": <实际总时长>,
  "narrative": "<一句话描述最终叙事弧>"
}}
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[curate-sel] 调用 {llm_model}（{len(selected_scenes)} 段勾选, "
                        f"target={target}s, brief={'有' if brief.strip() else '无'}）...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "selections" not in data:
            raise RuntimeError(f"curate_with_selection 返回无效: raw[:300]={raw[:300]!r}")
    finally:
        provider.model = original_model

    # 校验：所有 id 必须在勾选集合内（防 LLM 编造）
    selections = []
    for sel in data["selections"]:
        sid = sel.get("id")
        if sid not in selected_set:
            if logger:
                logger.warning(f"[curate-sel] 丢弃未勾选/不存在的 id: {sid}")
            continue
        s = next((x for x in selected_scenes if x["id"] == sid), None)
        if not s:
            continue
        a_dur = s["end"] - s["start"]
        d = float(sel.get("duration", min(max_dur, a_dur)))
        d = max(min_dur, min(max_dur, min(d, a_dur)))
        selections.append({
            "id": sid,
            "duration": d,
            "reason": sel.get("reason", ""),
            "scene": s,
        })

    # 归一化：仅当总可用时长 >= target 时严格 scale 到 target
    # 若总可用 < target（已经拉满了），保持原样不要硬 scale
    total = sum(s["duration"] for s in selections)
    if total_avail >= target and total > 0 and abs(total - target) > 0.5:
        scale = target / total
        for s in selections:
            a_dur = s["scene"]["end"] - s["scene"]["start"]
            new_d = s["duration"] * scale
            s["duration"] = round(max(min_dur, min(max_dur, min(new_d, a_dur))), 3)
        # 末段补差
        diff = target - sum(s["duration"] for s in selections)
        if abs(diff) > 0.01 and selections:
            last = selections[-1]
            a_dur = last["scene"]["end"] - last["scene"]["start"]
            last["duration"] = round(max(min_dur, min(max_dur, min(last["duration"] + diff, a_dur))), 3)

    if logger:
        total_after = sum(s["duration"] for s in selections)
        logger.info(f"[curate-sel] 输出 {len(selections)} 段, 总时长 {total_after:.2f}s "
                    f"(target={target}s, 可用={total_avail:.1f}s)")
        logger.info(f"[curate-sel] narrative: {data.get('narrative', '?')}")
        for i, s in enumerate(selections, 1):
            logger.info(f"  {i:>2}. {s['id']:<14} {s['duration']:.2f}s  {s['reason']}")

    # 把 narrative 挂到第一段上方便后续传出去
    if selections:
        selections[0]["narrative"] = data.get("narrative", "")
    return selections


def curate_with_instruction(scenes: list, current_items: list[dict],
                             instruction: str, target: float,
                             provider, llm_model: str,
                             logger=None,
                             min_dur: float = 0.6, max_dur: float = 4.0) -> list[dict]:
    """基于已有 storyboard + 用户自然语言指令，让 LLM 重新挑/排/分配时长。

    与 curate_with_selection 的差别：
    - 输入是"当前已剪辑的段"（current_items）+ 用户指令（不是勾选集合）
    - LLM 可以重排顺序、调整时长、在 pool 内换段
    - pool = current_items 用过的所有 scene id（不允许新增未在 pool 内的段）

    current_items: list[{"id":..., "duration":..., "reason":...}]（顺序=当前播放序）
    instruction: 用户自然语言指令（例如"把开头的特写换成倒酒镜头，整体压缩到 30 秒"）

    返回 selections: [{"id", "duration", "reason", "scene"}] 顺序=新播放顺序
    """
    import json as _json
    from video_worker.providers.base import parse_json_response

    pool_ids = [it["id"] for it in current_items if it.get("id")]
    if not pool_ids:
        if logger:
            logger.warning("[curate-inst] current_items 为空")
        return []
    pool_set = set(pool_ids)
    pool_scenes = [s for s in scenes if s["id"] in pool_set]
    if not pool_scenes:
        if logger:
            logger.warning("[curate-inst] pool 中没有匹配的 scene")
        return []
    pool_by_id = {s["id"]: s for s in pool_scenes}

    # pool 顺序：按 current_items 出现顺序（=当前播放序）
    ordered_pool_ids = [pid for pid in pool_ids if pid in pool_by_id]

    # 当前剪辑序展示
    current_block = []
    for i, it in enumerate(current_items, 1):
        sid = it.get("id")
        s = pool_by_id.get(sid)
        if not s:
            continue
        current_block.append({
            "order": i,
            "id": sid,
            "main_objects": s.get("main_objects") or [],
            "action_type": s.get("action_type") or "",
            "current_duration_s": round(float(it.get("duration", 0)), 2),
            "current_reason": it.get("reason", ""),
        })

    # 完整 pool 元数据（让 LLM 知道每段可用时长上限）
    pool_info = []
    total_avail = 0.0
    for sid in ordered_pool_ids:
        s = pool_by_id[sid]
        a_start = s.get("start", 0)
        a_end = s.get("end", 0)
        a_dur = a_end - a_start
        total_avail += a_dur
        pool_info.append({
            "id": sid,
            "main_objects": s.get("main_objects") or [],
            "action_type": s.get("action_type") or "",
            "available_duration_s": round(a_dur, 2),
        })

    prompt = f"""你是专业视频剪辑师。下面是**当前已剪辑好**的视频片段序列，用户希望基于此**再次编辑**。

**用户编辑指令**：
{instruction.strip()}

**目标时长**：{target} 秒（严格 ±5%）

**当前剪辑序列**（按当前播放顺序）：
{_json.dumps(current_block, ensure_ascii=False, indent=2)}

**可用片段池**（共 {len(pool_info)} 段，总可用时长 {total_avail:.1f}s；你只能用这些段，不能引入新段）：
{_json.dumps(pool_info, ensure_ascii=False, indent=2)}

**硬约束**：
1. **只能使用上述片段池中的段**——不能新增池外的段。
2. 可以重排顺序、调整时长、删除段、重复使用段（如果想用某段多次）。
3. 单段时长 [{min_dur}, {max_dur}] 秒，且不能超过该段的 available_duration_s。
4. 总时长严格 = {target} 秒。
5. 严格遵守用户指令的意图——如果指令说"压缩"就减少段数或时长；说"换"就在池内找替代；说"重排"就调整顺序。

**输出 JSON**（严格）：
{{
  "selections": [
    {{"id": "<scene_id>", "duration": <float>, "reason": "<15 字内说明本段在新序列里的作用>"}},
    ...
  ],
  "total": <实际总时长>,
  "narrative": "<一句话描述新叙事弧>",
  "changes": "<50 字内说明本次编辑做了什么调整>"
}}
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[curate-inst] 调 {llm_model}（pool {len(pool_info)} 段, target={target}s）...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "selections" not in data:
            raise RuntimeError(f"curate_with_instruction 返回无效: raw[:300]={raw[:300]!r}")
    finally:
        provider.model = original_model

    # 校验：所有 id 必须在 pool 内
    selections = []
    for sel in data["selections"]:
        sid = sel.get("id")
        if sid not in pool_set:
            if logger:
                logger.warning(f"[curate-inst] 丢弃池外/不存在的 id: {sid}")
            continue
        s = pool_by_id[sid]
        a_dur = s["end"] - s["start"]
        d = float(sel.get("duration", min(max_dur, a_dur)))
        d = max(min_dur, min(max_dur, min(d, a_dur)))
        selections.append({
            "id": sid,
            "duration": d,
            "reason": sel.get("reason", ""),
            "scene": s,
        })

    if not selections:
        if logger:
            logger.warning("[curate-inst] LLM 输出无有效段")
        return []

    # 归一化（同 curate_with_selection）
    total = sum(s["duration"] for s in selections)
    if total_avail >= target and total > 0 and abs(total - target) > 0.5:
        scale = target / total
        for s in selections:
            a_dur = s["scene"]["end"] - s["scene"]["start"]
            new_d = s["duration"] * scale
            s["duration"] = round(max(min_dur, min(max_dur, min(new_d, a_dur))), 3)
        diff = target - sum(s["duration"] for s in selections)
        if abs(diff) > 0.01 and selections:
            last = selections[-1]
            a_dur = last["scene"]["end"] - last["scene"]["start"]
            last["duration"] = round(max(min_dur, min(max_dur, min(last["duration"] + diff, a_dur))), 3)

    if logger:
        total_after = sum(s["duration"] for s in selections)
        logger.info(f"[curate-inst] 输出 {len(selections)} 段, 总时长 {total_after:.2f}s "
                    f"(target={target}s)")
        logger.info(f"[curate-inst] narrative: {data.get('narrative', '?')}")
        logger.info(f"[curate-inst] changes: {data.get('changes', '?')}")
        for i, s in enumerate(selections, 1):
            logger.info(f"  {i:>2}. {s['id']:<14} {s['duration']:.2f}s  {s['reason']}")

    selections[0]["narrative"] = data.get("narrative", "")
    selections[0]["changes"] = data.get("changes", "")
    return selections


def allocate_duration_llm(scenes: list, provider, llm_model: str,
                          target: float, logger,
                          min_dur: float = 0.4, max_dur: float = 2.5) -> list[float]:
    """调 LLM 给每段分配时长，总和 = target。"""
    original_model = provider.model
    provider.model = llm_model  # 临时切 LLM
    try:
        segs_json = []
        for i, sc in enumerate(scenes, 1):
            segs_json.append({
                "order": i,
                "id": sc["id"],
                "main_objects": sc.get("main_objects") or [],
                "action_type": sc.get("action_type") or "unknown",
                "highlight_score": sc.get("highlight_score", 5),
                "motion_score": sc.get("motion_score", 5),
                "visual_quality": sc.get("visual_quality", 5),
                "creation_time": sc.get("creation_time", "")[:19],
            })

        # 根据密度动态调整指导值
        avg_dur = target / max(len(segs_json), 1)
        if avg_dur < 0.5:
            # 密集剪辑（每段 < 0.5s）：放宽容差，允许更短
            guide = {
                "high_min": 0.6, "high_max": 1.5,
                "key_min": 0.4, "key_max": 1.0,
                "normal_min": 0.2, "normal_max": 0.5,
                "filler_min": 0.2, "filler_max": 0.3,
            }
            density_note = f"这是密集快剪场景（{len(segs_json)} 段压在 {target}s），平均每段 {avg_dur:.2f}s"
        else:
            guide = {
                "high_min": 1.8, "high_max": 2.5,
                "key_min": 1.2, "key_max": 2.0,
                "normal_min": 0.6, "normal_max": 1.2,
                "filler_min": 0.4, "filler_max": 0.8,
            }
            density_note = f"常规节奏（{len(segs_json)} 段 / {target}s）"

        prompt = f"""你是专业视频剪辑师。下面是按拍摄时间顺序排列的 {len(segs_json)} 个候选段，请分配每段时长。

**约束**：
1. 总时长**严格等于 {target} 秒**
2. 单段最短 {min_dur}s，最长 {max_dur}s

**场景**：{density_note}

**分配原则**：
- highlight_score ≥ 8 的高光段：{guide['high_min']}-{guide['high_max']}s
- 关键工序动作（cut / pour / shake / drop / stir 等）：{guide['key_min']}-{guide['key_max']}s
- 一般过程段：{guide['normal_min']}-{guide['normal_max']}s
- 重复或铺垫段：{guide['filler_min']}-{guide['filler_max']}s

**候选段 JSON**：
{json.dumps({"segments": segs_json}, ensure_ascii=False, indent=2)}

**输出格式**（严格 JSON）：
{{
  "allocations": [
    {{"id": "<segment_id>", "duration": <float>, "reason": "<简短理由，<30 字>"}},
    ...
  ],
  "total": <应当= {target}>
}}
"""
        logger.info(f"[llm] 调用 {llm_model} 分配 {len(segs_json)} 段时长（avg {avg_dur:.2f}s）...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "allocations" not in data:
            raise RuntimeError(f"LLM 返回无效: raw[:300]={raw[:300]!r}")

        id_to_dur = {a["id"]: float(a["duration"]) for a in data["allocations"]}
        durations = []
        for sc in scenes:
            d = id_to_dur.get(sc["id"])
            if d is None:
                logger.warning(f"[llm] 段 {sc['id']} 未分配，默认 {avg_dur:.2f}s")
                d = avg_dur
            durations.append(max(min_dur, min(max_dur, d)))

        total = sum(durations)
        logger.info(f"[llm] 分配原始总时长 {total:.2f}s（目标 {target}s）")
        # 按比例归一化到 target（LLM 不一定严格求和）
        if total > 0:
            scale = target / total
            durations = [round(d * scale, 3) for d in durations]
            diff = target - sum(durations)
            if abs(diff) > 0.01 and durations:
                durations[-1] = round(durations[-1] + diff, 3)

        return durations
    finally:
        provider.model = original_model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["glm", "doubao"], required=True)
    parser.add_argument("--input-dir", default=str(SOURCE_VIDEOS_DIR),
                        help="源视频目录（默认 tandao2）")
    parser.add_argument("--job-id", default=None,
                        help="job_id（默认按 provider 走 tandao2_hybrid_<provider>）")
    parser.add_argument("--target-duration", type=float, default=TARGET_DURATION,
                        help="目标视频时长秒（默认 30）")
    parser.add_argument("--min-dur", type=float, default=0.4,
                        help="单段最短时长（默认 0.4；密集剪辑可设 0.2）")
    parser.add_argument("--max-dur", type=float, default=2.5,
                        help="单段最长时长（默认 2.5）")
    args = parser.parse_args()

    pc = PROVIDER_CONFIG[args.provider]
    os.environ.setdefault(pc["api_key_env"], pc["api_key"])

    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger = logging.getLogger(f"hybrid_{args.provider}")

    job_id = args.job_id or pc["job_id"]
    job_dir = Path("jobs") / job_id
    input_dir = Path(args.input_dir)
    target_duration = args.target_duration

    cfg = JobConfig(
        job_id=job_id,
        input_path=str(input_dir),
        platform="general",
        style=Style.NARRATIVE,
        target_duration=int(target_duration),
        provider=pc["provider"],
        work_root="jobs",
        ffmpeg_path=str(resolve_ffmpeg(Path("tools/ffmpeg.exe"))),
        config_path=Path("configs/default.yaml"),
        natural_language_request=f"时间轴+AI混合方案 ({job_id})",
    )

    # === 1-4. preprocess + scene + frames + VLM ===
    yaml_cfg = config.load_yaml(cfg.config_path)
    config.apply_platform_overrides(cfg, yaml_cfg)
    p_cfg = config.get_platform_config(yaml_cfg, cfg.platform)

    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)
    (job_dir / "work").mkdir(parents=True)
    (job_dir / "output").mkdir(parents=True)
    (job_dir / "logs").mkdir(parents=True)

    logger.info("=== [1/7] 扫描素材 ===")
    clips_src = media_scan.scan_videos(cfg.input_path, logger)

    logger.info("=== [2/7] 预处理 ===")
    clips = preprocess.normalize(
        clips_src, job_dir, cfg,
        resolution=tuple(p_cfg.get("resolution", [720, 1280])),
        fps=p_cfg.get("fps", 25),
        strategy=yaml_cfg.get("preprocess", {}).get("resize_strategy", "blur_background"),
        blur_sigma=yaml_cfg.get("preprocess", {}).get("blur_sigma", 80.0),
        ffmpeg_path=cfg.ffmpeg_path, logger=logger,
    )

    logger.info("=== [3/7] 场景切分 ===")
    sd_cfg = yaml_cfg.get("scene_detect", {})
    scenes = scene_detect.split_scenes(
        clips, job_dir, cfg.ffmpeg_path,
        threshold=sd_cfg.get("threshold", 27.0),
        min_len_sec=sd_cfg.get("min_len_sec", 0.4),
        max_scene_len_sec=sd_cfg.get("max_scene_len_sec", 12.0),
        logger=logger,
    )

    logger.info("=== [4/7] 抽帧 ===")
    frames_map, analysis_scenes = frame_extract.make_frames_batch(
        scenes, job_dir, cfg.ffmpeg_path, logger=logger,
    )

    logger.info(f"=== [5/7] VLM 视觉分析（{pc['vlm_model']}）===")
    provider = vision_analyze.get_provider(
        cfg.provider.value, model=pc["vlm_model"], logger=logger,
    )
    analyzed = vision_analyze.analyze(
        analysis_scenes, frames_map, provider, job_dir, logger=logger,
    )

    # === 5. 每源 top-1 + 时间轴排序 ===
    logger.info("=== [6/7] 时间轴排序 + VLM-aware 去重 ===")
    ffmpeg = resolve_ffmpeg(Path("tools/ffmpeg.exe"))
    src_to_time = {}
    for src in sorted(input_dir.glob("*.MP4")):
        src_to_time[src.stem] = read_creation_time(ffmpeg, src)

    src_group = defaultdict(list)
    for a in analyzed:
        seg = a.id.rsplit("_", 1)[0]
        src_group[seg].append(a)

    best_per_src = {}
    for seg, scenes_per_src in src_group.items():
        def score(a):
            return a.highlight_score * 0.5 + a.visual_quality * 0.3 + a.motion_score * 0.2
        best_per_src[seg] = max(scenes_per_src, key=score)

    sorted_segs = sorted(
        best_per_src.keys(),
        key=lambda s: src_to_time.get(s, "9999"),
    )
    sorted_scenes = []
    for seg in sorted_segs:
        a = best_per_src[seg]
        sc = a.model_dump()
        sc["creation_time"] = src_to_time.get(seg, "")
        sc["source_id"] = seg
        sorted_scenes.append(sc)

    logger.info(f"  每源 top-1：{len(sorted_scenes)} 段（按 creation_time 升序）")

    # 同时支持 VLM 标签去重 + pHash 像素去重（任一匹配即合并）
    frames_seq_dir = job_dir / "work" / "frames_seq"
    survivors, dropped = vlm_aware_dedup(
        sorted_scenes,
        jaccard_threshold=0.5,
        frames_seq_dir=frames_seq_dir,
        phash_threshold=10,  # hash_size=8 下约 15% 位差
        phash_hash_size=8,
    )
    logger.info(f"  VLM-aware 去重后：{len(survivors)} 段（淘汰 {len(dropped)}）")
    for d in dropped:
        logger.info(f"    drop {d['id']} (kept {d['kept']}, score {d['highlight']} < {d['kept_highlight']})")

    # 保存中间结果便于排查
    (job_dir / "work" / "timeaxis_candidates.json").write_text(
        json.dumps(
            {"sorted_scenes": sorted_scenes, "dropped": dropped, "survivors": survivors},
            ensure_ascii=False, indent=2, default=str,
        ),
        encoding="utf-8",
    )

    # === 6. LLM 时长分配 ===
    logger.info(f"=== [7/7] LLM 时长分配（{pc['llm_model']}）===")
    durations = allocate_duration_llm(
        survivors, provider, pc["llm_model"], target_duration, logger,
                                  min_dur=args.min_dur, max_dur=args.max_dur,
    )

    items = []
    for i, (sc, dur) in enumerate(zip(survivors, durations), 1):
        a_start = sc["start"]
        a_end = sc["end"]
        a_dur = a_end - a_start
        desired = min(dur, a_dur)
        use_start = a_start + (a_dur - desired) / 2
        use_end = use_start + desired
        items.append(StoryboardItem(
            order=i,
            id=sc["id"],
            cut_duration=round(use_end - use_start, 3),
            subtitle=None,
            use_start=round(use_start, 3),
            use_end=round(use_end, 3),
            reason=f"hybrid-{args.provider}",
        ))

    board = Storyboard(
        narrative=f"檀道宣传片（时间轴+AI混合方案 - {args.provider}）",
        target_duration_sec=int(target_duration),
        expected_duration_sec=sum(it.cut_duration for it in items),
        selected=items,
    )

    (job_dir / "work" / "storyboard_hybrid.json").write_text(
        json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    # === 7. 渲染 ===
    logger.info("=== 渲染 ===")
    r_cfg = yaml_cfg.get("render", {})
    final_video = render.render(
        board, analyzed, cfg, job_dir,
        color_grade=p_cfg.get("color_grade", "natural"),
        bgm_atempo=p_cfg.get("bgm_atempo", 1.0),
        ass_fontsize=p_cfg.get("ass", {}).get("fontsize", 30),
        ass_outline=p_cfg.get("ass", {}).get("outline", 2.5),
        ass_marginv=p_cfg.get("ass", {}).get("marginv", 100),
        crf=r_cfg.get("crf", 20),
        bgm_volume=r_cfg.get("bgm_volume", 0.85),
        fade_in=r_cfg.get("fade_in_sec", 1.0),
        fade_out=r_cfg.get("fade_out_sec", 1.5),
        xfade_dur=r_cfg.get("xfade_dur", 0.0),
        logger=logger,
    )

    # === 总结 ===
    print()
    print("="*60)
    print(f"Provider: {args.provider}")
    print(f"Job: {job_id}")
    print(f"VLM 模型: {pc['vlm_model']}（fresh 42 次调用）")
    print(f"LLM 模型: {pc['llm_model']}（fresh 1 次调用）")
    print(f"输出: {final_video}")
    print(f"段数: {len(items)}（淘汰 {len(dropped)} 重复）")
    print(f"总时长: {board.expected_duration_sec:.2f}s")
    print()
    print("段详情（按 creation_time 排序）:")
    for it, sc in zip(items, survivors):
        ct = sc.get("creation_time", "")[:19]
        objs = "/".join(sc.get("main_objects") or [])[:25]
        print(f"  {it.order:>2}. {it.id:<12} ct={ct} "
              f"[{it.use_start:.2f}-{it.use_end:.2f}]={it.cut_duration:.2f}s "
              f"action={sc.get('action_type','?'):<12} "
              f"score={sc.get('highlight_score',0)} "
              f"objs={objs}")


if __name__ == "__main__":
    main()
