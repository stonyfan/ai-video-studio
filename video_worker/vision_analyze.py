"""
AI 视觉分析：调用 provider 适配器分析每个场景
- 默认 provider: zai（包装 mcp__zai-mcp-server__analyze_image）
- 阶段 2 增加 qwen-vl / doubao
"""
from __future__ import annotations
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from .validators import Scene, AnalyzedScene


SCENE_PROMPT_TEMPLATE = """玉兰花马天尼调酒视频。同一场景 3 个时刻横排（左25%/中50%/右75%）。判断哪帧是最佳瞬间。

只返回 JSON，无其他文字：
{{"best_frame": "left|mid|right", "cut_duration": <0.5-1.5浮点数>, "best_moment": "<5-10字>", "main_object": "<主要物体>", "action_type": "<preparation|pouring|mixing|serving|decoration>"}}

判断：动作高潮（液体接触/刀切/挤压）> 静态准备。cut_duration 紧凑动作0.5-1.0s，长过程1.0-1.5s。"""


def parse_json_response(text: str) -> Optional[dict]:
    """从 LLM 响应中提取 JSON（容错）"""
    try:
        return json.loads(text)
    except Exception:
        # 尝试从 markdown 代码块提取
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
        # 尝试提取第一个 {...}
        m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def analyze_scene(scene: Scene, triplet_path: Path,
                  provider, logger: Optional[logging.Logger] = None) -> AnalyzedScene:
    """
    单场景分析。
    provider 必须实现 analyze_image(image_path, prompt) -> str 接口
    """
    raw = provider.analyze_image(str(triplet_path), SCENE_PROMPT_TEMPLATE)
    data = parse_json_response(raw) or {}
    if logger:
        logger.debug(f"[analyze] {scene.id}: {data}")

    return AnalyzedScene(
        id=scene.id,
        src=scene.src,
        start=scene.start,
        end=scene.end,
        dur=scene.dur,
        best_frame=data.get("best_frame", "mid"),
        cut_duration=float(data.get("cut_duration", 1.0)),
        best_moment=data.get("best_moment", ""),
        main_object=data.get("main_object", ""),
        action_type=data.get("action_type", "unknown"),
    )


def analyze(scenes: list[Scene], triplets: dict[str, Path],
            provider, job_dir: Path,
            logger: Optional[logging.Logger] = None) -> list[AnalyzedScene]:
    """
    批量分析（顺序，后续可改并发）
    返回 analyzed.json 持久化
    """
    out = []
    for sc in scenes:
        tp = triplets.get(sc.id)
        if not tp:
            if logger:
                logger.warning(f"[analyze] 缺三联图 {sc.id}")
            continue
        try:
            ana = analyze_scene(sc, tp, provider, logger)
            out.append(ana)
        except Exception as e:
            if logger:
                logger.error(f"[analyze] 失败 {sc.id}: {e}")

    out_path = job_dir / "work" / "analyzed.json"
    out_path.write_text(
        json.dumps([a.model_dump() for a in out], ensure_ascii=False, indent=2,
                   default=str),
        encoding="utf-8",
    )
    if logger:
        logger.info(f"[analyze] 完成 {len(out)}/{len(scenes)}")
    return out


def get_provider(provider_name: str, api_key: Optional[str] = None):
    """工厂方法：按 name 拿 provider 实例"""
    if provider_name == "zai":
        from .providers.zai_provider import ZaiProvider
        return ZaiProvider()
    elif provider_name == "qwen-vl":
        # 阶段 2 填充
        raise NotImplementedError("qwen-vl provider 待阶段 2 实现")
    elif provider_name == "doubao":
        raise NotImplementedError("doubao provider 待阶段 2 实现")
    else:
        raise ValueError(f"未知 provider: {provider_name}")
