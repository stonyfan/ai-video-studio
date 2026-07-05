"""
配置加载：YAML + 环境变量 + JobConfig 合并
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Optional
import yaml

from .validators import JobConfig, Platform, Style, Provider


DEFAULT_CONFIG_PATH = Path("configs/default.yaml")


def load_yaml(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def get_platform_config(yaml_cfg: dict, platform: Platform | str) -> dict:
    """拿平台配置"""
    p = platform.value if isinstance(platform, Platform) else platform
    return yaml_cfg.get("platforms", {}).get(p, {})


def get_style_config(yaml_cfg: dict, style: Style | str) -> dict:
    s = style.value if isinstance(style, Style) else style
    return yaml_cfg.get("styles", {}).get(s, {})


def get_provider_config(yaml_cfg: dict) -> dict:
    return yaml_cfg.get("provider", {})


def get_path_config(yaml_cfg: dict) -> dict:
    return yaml_cfg.get("paths", {})


def resolve_provider_api_key(yaml_cfg: dict) -> Optional[str]:
    """从环境变量取 provider api key"""
    cfg = get_provider_config(yaml_cfg)
    env_name = cfg.get("api_key_env")
    if env_name:
        return os.environ.get(env_name)
    return None


def apply_platform_overrides(job: JobConfig, yaml_cfg: dict) -> JobConfig:
    """
    用 YAML 配置覆盖 JobConfig 默认值：
    - platform 决定 resolution/fps/color_grade/bgm_atempo
    - style 决定 cut_duration_range
    """
    p_cfg = get_platform_config(yaml_cfg, job.platform)
    s_cfg = get_style_config(yaml_cfg, job.style)

    # ffmpeg_path 从 YAML 拿（如果存在）
    p_paths = get_path_config(yaml_cfg)
    if p_paths.get("ffmpeg") and job.ffmpeg_path == Path("tools/ffmpeg.exe"):
        # 只在默认值时覆盖（用户没显式指定）
        try:
            from pathlib import Path as P
            job = job.model_copy(update={"ffmpeg_path": P(p_paths["ffmpeg"])})
        except Exception:
            pass

    if p_paths.get("work_root") and job.work_root == Path("jobs"):
        try:
            from pathlib import Path as P
            job = job.model_copy(update={"work_root": P(p_paths["work_root"])})
        except Exception:
            pass

    return job


def effective_cut_duration(yaml_cfg: dict, platform: Platform | str,
                           style: Style | str) -> float:
    """平台默认 cut_duration（按风格上下浮动）"""
    p_cfg = get_platform_config(yaml_cfg, platform)
    s_cfg = get_style_config(yaml_cfg, style)
    base = p_cfg.get("cut_duration", 1.0)
    rng = s_cfg.get("cut_duration_range", [base, base])
    # 取范围中点，但优先用平台 base
    if rng[0] <= base <= rng[1]:
        return base
    return (rng[0] + rng[1]) / 2
