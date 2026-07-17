"""
video_worker/timeline_dedup.py — creation_time 读取 + LLM 故事阶段聚类

由 job.py 在 orchestration_mode == "llm" 时调用：
1. read_creation_time 解析每个 src 的真实拍摄时间
2. cluster_by_timeline 调 LLM 把按时间序的 scenes 分成故事阶段

不去做 dedup（per-src 去重仍由 storyboard.deduplicate 负责），不依赖 scripts/。
"""
from __future__ import annotations
import logging
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .validators import AnalyzedScene


def read_creation_time(ffmpeg: Path, video_path: Path) -> str:
    """读 MP4 creation_time（按 bytes 读避免 GBK 解码崩）。"""
    try:
        result = subprocess.run(
            [str(ffmpeg), "-hide_banner", "-i", str(video_path)],
            capture_output=True, timeout=10,
        )
        err_text = (result.stderr or b"").decode("utf-8", errors="replace")
        m = re.search(r"creation_time\s*:\s*(\S+)", err_text)
        return m.group(1) if m else ""
    except Exception:
        return ""


def read_src_creation_times(input_dir: Path, ffmpeg: Path,
                            logger: Optional[logging.Logger] = None) -> dict[str, str]:
    """扫描 input_dir 下所有视频，返回 {src_stem: creation_time}。

    用于注入 AnalyzedScene 的时间序信息（替代不可靠的 id 自然序）。
    """
    src_to_time: dict[str, str] = {}
    if not input_dir.exists():
        return src_to_time
    exts = (".mp4", ".MP4", ".mov", ".MOV", ".avi", ".AVI", ".mkv", ".MKV")
    for src in sorted(input_dir.iterdir()):
        if not src.is_file() or src.suffix not in exts:
            continue
        try:
            src_to_time[src.stem] = read_creation_time(ffmpeg, src)
        except Exception as e:
            if logger:
                logger.warning(f"[timeline] read_creation_time 失败 {src.name}: {e}")
            src_to_time[src.stem] = ""
    return src_to_time


def cluster_by_timeline(scenes: list[dict], provider, llm_model: str,
                        logger: Optional[logging.Logger] = None,
                        skill_snippet: str = "",
                        style_hint: str = "") -> list[dict]:
    """LLM 把按时间序的 scenes 分成故事阶段（仅聚类，不去重）。

    输入 scenes 必须已按 creation_time 升序排好。每段是 dict（AnalyzedScene.model_dump() 也行），
    至少含 id / main_objects / action_type / highlight_score。

    skill_snippet: 可选，来自 configs/skills/<name>/SKILL.md 的 Prompt Snippet，注入到 prompt 末尾。

    style_hint: 可选，多变体生成时的风格偏移（如"动作密集段优先"）。注入到聚类规则后，
        让 LLM 在 stage 主题/representative 选择上偏向该风格。空字符串=无偏移。

    返回 stages: [
        {"stage": 1, "theme": "...", "members": [id, ...],
         "representative": id, "score_range": [min, max], "size": N},
        ...
    ]
    """
    import json as _json
    from .providers.base import parse_json_response

    if not scenes:
        return []

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
    skill_block = f"\n\n**当前 skill 指导（聚类时参考这个叙事骨架，让 stage theme 贴合该 skill）**：\n{skill_snippet}" if skill_snippet else ""
    style_block = f"\n\n**本次风格偏移（多变体生成时使用，影响 stage 主题命名和 representative 选择倾向）**：\n{style_hint}" if style_hint else ""
    prompt = f"""你是专业视频剪辑师。下面是按**拍摄时间顺序**排列的 {len(segs)} 个候选段。
请把它们分成"故事阶段"——一个阶段是时间上**连续**、属于同一动作流程或场景的片段集合。

**目标阶段数：约 {target_stages} 个**（不要过碎）。

**关键规则**（按重要性排序）：
1. **只能合并列表中相邻或连续的段**。一个 stage 的 order 必须是连续整数（[3,4,5] 可以；[3,5,7] 不行）。
2. **动作流程一致就合并**：相邻段的 action_type 相同（都是"倒酒"/"摇酒"/"切水果"/"摇镜头特写"等），即使 main_objects 略有差异，**必须合并为同一阶段**。
3. **跨语义才拆分**：只有中间明确隔了完全不同的动作（如"调酒过程"中插入"成品展示"），才必须分成两个阶段。
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
5. **总阶段数目标 {target_stages} 个左右，不要超过 {target_stages * 2} 个**{skill_block}{style_block}
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[cluster-timeline] 调用 {llm_model} 给 {len(segs)} 段分阶段"
                        f"（skill={'有' if skill_snippet else '无'}）...")
        raw = provider.chat(prompt, max_tokens=8192)
        data = parse_json_response(raw)
        if not data or "stages" not in data:
            raise RuntimeError(f"LLM timeline cluster 返回无效: raw[:300]={raw[:300]!r}")
    finally:
        provider.model = original_model

    order_to_stage: dict[int, int] = {}
    stage_themes: dict[int, str] = {}
    for i, st in enumerate(data["stages"]):
        theme = st.get("theme", f"stage_{i+1}")
        members = st.get("members", [])
        stage_themes[i] = theme
        if members:
            sorted_m = sorted(members)
            for j in range(1, len(sorted_m)):
                if sorted_m[j] != sorted_m[j-1] + 1:
                    if logger:
                        logger.warning(f"  [timeline] stage {i+1} '{theme}' members 不连续: {sorted_m}")
                    break
        for m in members:
            order_to_stage[m] = i

    stage_members: dict[int, list[dict]] = defaultdict(list)
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

    if logger:
        for st in stages_out:
            logger.info(f"  [stage {st['stage']}] {st['theme']}（{st['size']}段→代表 {st['representative']}）: "
                        f"{st['members']}")
    return stages_out
