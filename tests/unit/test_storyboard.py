"""单元测试：validators"""
import pytest
from pathlib import Path
from pydantic import ValidationError

from video_worker.validators import (
    JobConfig, JobResult, JobStatus, Platform, Style, Provider,
    Scene, AnalyzedScene, StoryboardItem, Storyboard, ErrorInfo, CostBreakdown,
)


def test_job_config_minimal(tmp_path):
    """最小 JobConfig"""
    src = tmp_path / "input"
    src.mkdir()
    c = JobConfig(job_id="test_001", input_path=src)
    assert c.job_id == "test_001"
    assert c.platform == Platform.GENERAL
    assert c.style == Style.FAST_CUT
    assert c.target_duration == 30


def test_job_config_invalid_id(tmp_path):
    """job_id 含非法字符"""
    src = tmp_path / "input"
    src.mkdir()
    with pytest.raises(ValidationError):
        JobConfig(job_id="test/001", input_path=src)


def test_job_config_invalid_duration(tmp_path):
    """时长越界"""
    src = tmp_path / "input"
    src.mkdir()
    with pytest.raises(ValidationError):
        JobConfig(job_id="t", input_path=src, target_duration=1)
    with pytest.raises(ValidationError):
        JobConfig(job_id="t", input_path=src, target_duration=1000)


def test_job_config_input_not_exists(tmp_path):
    """input_path 不存在"""
    with pytest.raises(ValidationError):
        JobConfig(job_id="t", input_path=tmp_path / "no_such")


def test_scene_serialization():
    """Scene 序列化"""
    s = Scene(id="1-1_0", src=Path("a.mp4"), seg="1-1", sc_idx=0,
              start=0.0, end=2.0, dur=2.0)
    d = s.model_dump()
    assert d["id"] == "1-1_0"
    assert d["dur"] == 2.0


def test_analyzed_scene_defaults():
    a = AnalyzedScene(id="x", src=Path("x.mp4"), start=0, end=1, dur=1,
                      best_frame="mid", cut_duration=0.8,
                      best_moment="m", main_object="o", action_type="pouring")
    assert a.best_frame == "mid"


def test_storyboard_round_trip():
    items = [
        StoryboardItem(order=1, id="a", cut_duration=0.8, use_start=0, use_end=0.8),
        StoryboardItem(order=2, id="b", cut_duration=1.0, use_start=0.5, use_end=1.5),
    ]
    b = Storyboard(narrative="test", target_duration_sec=15,
                   expected_duration_sec=1.8, selected=items)
    d = b.model_dump()
    assert len(d["selected"]) == 2


def test_job_result_failed():
    r = JobResult(
        job_id="t", status=JobStatus.FAILED,
        error=ErrorInfo(stage="render", code="FFMPEG_ERROR", message="fail"),
    )
    assert r.status == JobStatus.FAILED
    assert r.error.code == "FFMPEG_ERROR"
