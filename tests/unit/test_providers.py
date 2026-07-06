"""单元测试：providers + vision_analyze"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from video_worker.providers.base import (
    parse_json_response, validate_schema, ProviderStats, CallRecord,
    VisionProvider, ProviderError, ProviderUnavailable,
)
from video_worker.providers.zai_provider import MockProvider, ZaiProvider
from video_worker.vision_analyze import (
    load_prompts, get_template, render_template, get_triplet_prompt,
    analyze_scene, get_provider,
)
from video_worker.validators import Scene


# ===== parse_json_response =====

def test_parse_simple_json():
    text = '{"a": 1, "b": 2}'
    assert parse_json_response(text) == {"a": 1, "b": 2}


def test_parse_markdown_codeblock():
    text = '```json\n{"x": 1}\n```'
    assert parse_json_response(text) == {"x": 1}


def test_parse_text_with_json():
    text = '先描述一下，然后返回 {"k": "v"} 结束'
    assert parse_json_response(text) == {"k": "v"}


def test_parse_nested_json():
    text = '{"outer": {"inner": 1}, "n": 2}'
    d = parse_json_response(text)
    assert d["outer"]["inner"] == 1


def test_parse_invalid():
    assert parse_json_response("") is None
    assert parse_json_response("no json here") is None


# ===== validate_schema =====

def test_validate_schema_ok():
    assert validate_schema({"a": 1, "b": 2}, ["a", "b"])


def test_validate_schema_missing():
    assert not validate_schema({"a": 1}, ["a", "b"])


# ===== ProviderStats =====

def test_provider_stats_accumulate():
    stats = ProviderStats()
    stats.add(CallRecord(provider="x", image_path="a.jpg", prompt_chars=10,
                        success=True, duration_sec=1.0,
                        input_tokens=100, output_tokens=50,
                        estimated_cost_cny=0.5))
    stats.add(CallRecord(provider="x", image_path="b.jpg", prompt_chars=10,
                        success=False, duration_sec=0.5, error="timeout"))
    assert stats.total_calls == 2
    assert stats.success_count == 1
    assert stats.total_tokens == 150
    assert stats.total_cost_cny == 0.5
    assert stats.success_rate == 0.5


# ===== MockProvider =====

def test_mock_provider_returns_json():
    p = MockProvider()
    text = p.analyze_image("fake.jpg", "test prompt")
    d = parse_json_response(text)
    assert d["best_frame"] == "mid"
    assert d["cut_duration"] == 0.8


def test_mock_provider_custom_response():
    p = MockProvider('{"best_frame": "left", "cut_duration": 1.5}')
    text = p.analyze_image("fake.jpg", "test")
    d = parse_json_response(text)
    assert d["best_frame"] == "left"


# ===== 工厂方法 =====

def test_get_provider_mock():
    p = get_provider("mock")
    assert p.name == "mock"


def test_get_provider_qwen_vl_no_key():
    """Qwen-VL 没 api_key 应报 ProviderUnavailable"""
    import os
    os.environ.pop("DASHSCOPE_API_KEY", None)
    os.environ.pop("QWEN_VL_API_KEY", None)
    with pytest.raises(ProviderUnavailable):
        get_provider("qwen-vl")


def test_get_provider_unknown():
    with pytest.raises(ValueError):
        get_provider("unknown_provider")


# ===== ZaiProvider (mock MCP caller) =====

def test_zai_provider_with_mcp_caller():
    mock_caller = MagicMock(return_value='{"best_frame": "right"}')
    p = ZaiProvider(mcp_caller=mock_caller)
    text = p.analyze_image("triplet.jpg", "prompt")
    assert text == '{"best_frame": "right"}'
    mock_caller.assert_called_once_with("triplet.jpg", "prompt")
    assert p.stats.total_calls == 1
    assert p.stats.success_count == 1


def test_zai_provider_without_caller_raises():
    p = ZaiProvider()
    with pytest.raises(RuntimeError):
        p.analyze_image("triplet.jpg", "prompt")


# ===== Prompt 模板 =====

def test_load_prompts():
    """从 configs/prompts.yaml 加载"""
    cfg = load_prompts(Path("configs/prompts.yaml"))
    assert "templates" in cfg
    assert "triplet_detect" in cfg["templates"]


def test_get_template_default():
    cfg = load_prompts(Path("configs/prompts.yaml"))
    tpl = get_template(cfg, "triplet_detect", "default")
    assert "JSON" in tpl
    assert "best_frame" in tpl


def test_get_template_travel():
    cfg = load_prompts(Path("configs/prompts.yaml"))
    tpl = get_template(cfg, "triplet_detect", "travel")
    assert "vlog" in tpl.lower()


def test_render_template_substitutes_vertical():
    cfg = load_prompts(Path("configs/prompts.yaml"))
    tpl = "{vertical_prompt} 内容部分"
    out = render_template(tpl, cfg, "travel")
    assert "旅游" in out


def test_get_triplet_prompt_convenience():
    """便捷方法能拿完整 prompt"""
    p = get_triplet_prompt("default")
    assert "best_frame" in p
    assert "{vertical_prompt}" not in p  # 占位符已替换


# ===== analyze_scene（端到端 mock） =====

def test_analyze_scene_with_mock_provider(tmp_path):
    """用 MockProvider 跑 analyze_scene"""
    # 创建假的 triplet 图片
    from PIL import Image
    img_path = tmp_path / "triplet.jpg"
    Image.new("RGB", (360, 640), (100, 100, 100)).save(img_path)

    sc = Scene(id="test_0", src=tmp_path / "x.mp4", seg="test", sc_idx=0,
               start=0.0, end=2.0, dur=2.0)
    provider = MockProvider('{"best_frame": "left", "cut_duration": 1.2, '
                            '"best_moment": "精彩瞬间", "main_object": "主体", '
                            '"action_type": "landscape"}')
    ana = analyze_scene(sc, img_path, provider)
    assert ana.id == "test_0"
    assert ana.best_frame == "left"
    assert ana.cut_duration == 1.2
    assert ana.best_moment == "精彩瞬间"


def test_analyze_scene_invalid_json_falls_back(tmp_path):
    """provider 返回非 JSON 时用默认值"""
    from PIL import Image
    img_path = tmp_path / "triplet.jpg"
    Image.new("RGB", (360, 640), (100, 100, 100)).save(img_path)

    sc = Scene(id="test_0", src=tmp_path / "x.mp4", seg="test", sc_idx=0,
               start=0.0, end=2.0, dur=2.0)
    provider = MockProvider("这不是 JSON")
    ana = analyze_scene(sc, img_path, provider)
    # 默认值兜底
    assert ana.best_frame == "mid"
    assert ana.cut_duration == 1.0
