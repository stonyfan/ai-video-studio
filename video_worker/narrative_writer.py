"""剪辑思路叙述生成：plan 后调一次 LLM，让它解释为什么这么挑、这么排。

只在 orchestration_mode in {llm, default} 时调用（timeline 是纯算法，没"思考"）。
"""
from __future__ import annotations
import logging
from typing import Optional

from .validators import AnalyzedScene, Storyboard


MODE_LABEL = {
    "timeline": "时间序编排（按拍摄顺序铺开）",
    "llm": "故事阶段编排（LLM 聚类 + 阶段代表制）",
    "default": "混合编排（LLM 挑选 + 去重 + 时间序）",
}


def write_narrative(
    board: Storyboard,
    analyzed: list[AnalyzedScene],
    orchestration_mode: str,
    provider,
    llm_model: str,
    target: int,
    logger: Optional[logging.Logger] = None,
    skill_snippet: str = "",
) -> str:
    """调 LLM 写一段 100-200 字的剪辑思路说明。

    失败时返回模板 narrative（不抛错，不影响主流程）。
    """
    if orchestration_mode not in MODE_LABEL:
        return board.narrative

    analyzed_by_id = {a.id: a for a in analyzed}
    items_info = []
    for it in board.selected:
        sc = analyzed_by_id.get(it.id)
        if not sc:
            continue
        items_info.append({
            "order": it.order,
            "id": it.id,
            "main_objects": sc.main_objects or [],
            "action_type": sc.action_type or "",
            "cut_duration_s": round(it.cut_duration, 2),
            "use_range_s": [round(it.use_start, 2), round(it.use_end, 2)],
        })

    if not items_info:
        return board.narrative

    mode_label = MODE_LABEL[orchestration_mode]
    items_block = _format_items(items_info)
    skill_block = f"\n\n**当前 skill**（剪辑思路要呼应这个叙事骨架）：\n{skill_snippet}" if skill_snippet else ""

    prompt = f"""你是专业视频剪辑师，刚完成了一段 {target} 秒视频的剪辑。请写一段说明，**方便用户后续用自然语言再次编辑**（如"把第 3 段摇酒挪到最后"）。

**编排模式**：{mode_label}

**最终剪辑结果（按播放顺序）**：
{items_block}

**输出格式**（严格遵守，两部分都要写）：

【画面流程】
按播放顺序，每段一行：「序号. 简短描述（时长s）」。描述用 6-12 字概括画面（动作+主体，如"佛手入水溅水花"、"刀切佛手果"、"双手抛接雪克壶"），**让用户能对应到具体段**。所有段都要列，不能省略。

【剪辑思路】
150-200 字中文，说明：
1. 整体叙事弧（开头/中段/收尾如何设计）
2. 至少提及一处节奏/转场/对比的设计考量
3. 呼应当前 skill 的叙事骨架（若有）

**要求**：
- 两部分都要写，先【画面流程】后【剪辑思路】
- 不要任何 markdown 标记（不要 ** 加粗）、不要 JSON、不要 "以下是..." 开场白
- 直接输出，【画面流程】和【剪辑思路】用方括号标记分段{skill_block}
"""

    original_model = provider.model
    provider.model = llm_model
    try:
        if logger:
            logger.info(f"[narrative] 调 {llm_model} 写剪辑思路（{len(items_info)} 段）...")
        raw = provider.chat(prompt, max_tokens=1200)
        narrative = raw.strip()
        # 简单清洗：去 markdown 包装
        for prefix in ["以下是剪辑思路说明：", "剪辑思路：", "剪辑思路说明："]:
            if narrative.startswith(prefix):
                narrative = narrative[len(prefix):].strip()
        narrative = narrative.strip("`").strip()
        if not narrative or len(narrative) < 20:
            if logger:
                logger.warning(f"[narrative] LLM 返回过短，用模板兜底: {narrative[:80]!r}")
            return board.narrative
        if logger:
            logger.info(f"[narrative] 完成（{len(narrative)} 字）")
        return narrative
    except Exception as e:
        if logger:
            logger.warning(f"[narrative] LLM 调用失败，用模板兜底: {e}")
        return board.narrative
    finally:
        provider.model = original_model


def _format_items(items: list[dict]) -> str:
    lines = []
    for it in items:
        objs = "、".join(it["main_objects"][:3]) if it["main_objects"] else "—"
        lines.append(
            f"{it['order']}. [{it['action_type']}] {objs} "
            f"({it['cut_duration_s']}s)"
        )
    return "\n".join(lines)
