"""
AI 视觉分析：调用 provider 适配器分析每个场景
- 默认 provider: qwen-vl（阿里）
- 也支持 doubao（字节）/ zai（MCP）/ mock（测试）
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from .validators import Scene, AnalyzedScene
from .providers.base import parse_json_response, validate_schema


PROMPTS_DEFAULT_PATH = Path("configs/prompts.yaml")


def load_prompts(path: Path = PROMPTS_DEFAULT_PATH) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def get_template(prompts_cfg: dict, task: str, vertical: str = "default") -> str:
    """从 prompts 配置取 prompt 模板"""
    templates = prompts_cfg.get("templates", {})
    task_cfg = templates.get(task, {})
    # 先按 vertical 找，找不到 fallback default
    tpl = task_cfg.get(vertical) or task_cfg.get("default", "")
    if not tpl:
        raise ValueError(f"prompt 模板不存在: task={task} vertical={vertical}")
    return tpl


def render_template(template: str, prompts_cfg: dict, vertical: str = "default") -> str:
    """填充 {vertical_prompt} 占位符"""
    verticals = prompts_cfg.get("verticals", {})
    vertical_prompt = verticals.get(vertical, verticals.get("default", ""))
    return template.replace("{vertical_prompt}", vertical_prompt)


def get_triplet_prompt(vertical: str = "default",
                       prompts_path: Path = PROMPTS_DEFAULT_PATH) -> str:
    """便捷方法：拿三联图检测 prompt"""
    cfg = load_prompts(prompts_path)
    tpl = get_template(cfg, "triplet_detect", vertical)
    return render_template(tpl, cfg, vertical)


def analyze_scene(scene: Scene, triplet_path: Path,
                  provider, prompt: Optional[str] = None,
                  logger: Optional[logging.Logger] = None) -> AnalyzedScene:
    """单场景分析"""
    if prompt is None:
        prompt = get_triplet_prompt()
    raw = provider.analyze_image(str(triplet_path), prompt)
    data = parse_json_response(raw) or {}
    if logger:
        logger.debug(f"[analyze] {scene.id}: {data}")

    # schema 校验 + 默认值兜底
    if not validate_schema(data, ["best_frame", "cut_duration"]):
        if logger:
            logger.warning(f"[analyze] {scene.id} schema 不全: {data}")

    try:
        cut_dur = float(data.get("cut_duration", 1.0))
    except (TypeError, ValueError):
        cut_dur = 1.0

    return AnalyzedScene(
        id=scene.id,
        src=scene.src,
        start=scene.start,
        end=scene.end,
        dur=scene.dur,
        best_frame=data.get("best_frame", "mid"),
        cut_duration=cut_dur,
        best_moment=data.get("best_moment", ""),
        main_object=data.get("main_object", ""),
        action_type=data.get("action_type", "unknown"),
    )


def analyze(scenes: list[Scene], triplets: dict[str, Path],
            provider, job_dir: Path,
            vertical: str = "default",
            prompt: Optional[str] = None,
            logger: Optional[logging.Logger] = None) -> list[AnalyzedScene]:
    """批量分析（顺序），持久化 analyzed.json"""
    if prompt is None:
        prompt = get_triplet_prompt(vertical)
    if logger:
        logger.info(f"[analyze] prompt 长度 {len(prompt)} chars, vertical={vertical}")

    out = []
    for sc in scenes:
        tp = triplets.get(sc.id)
        if not tp:
            if logger:
                logger.warning(f"[analyze] 缺三联图 {sc.id}")
            continue
        try:
            ana = analyze_scene(sc, tp, provider, prompt, logger)
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


def get_provider(provider_name: str, api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 mcp_caller=None,
                 logger=None):
    """工厂方法：按 name 拿 provider 实例"""
    name = provider_name.lower()

    if name == "zai":
        from .providers.zai_provider import ZaiProvider
        return ZaiProvider(mcp_caller=mcp_caller, logger=logger)
    elif name == "qwen-vl":
        from .providers.qwen_vl import QwenVLProvider
        kwargs = {"api_key": api_key}
        if model:
            kwargs["model"] = model
        if logger:
            kwargs["logger"] = logger
        return QwenVLProvider(**kwargs)
    elif name == "doubao":
        from .providers.doubao import DoubaoProvider
        kwargs = {"api_key": api_key}
        if model:
            kwargs["model"] = model
        if logger:
            kwargs["logger"] = logger
        return DoubaoProvider(**kwargs)
    elif name == "mock":
        from .providers.zai_provider import MockProvider
        return MockProvider()
    else:
        raise ValueError(f"未知 provider: {provider_name}")
