"""单元测试：storyboard"""
from pathlib import Path

from video_worker.validators import AnalyzedScene, JobConfig
from video_worker import storyboard


def test_compute_cut_left():
    us, ue = storyboard.compute_cut(0.0, 6.0, "left", 1.0)
    assert us == 0.0 and ue == 1.0


def test_compute_cut_right():
    us, ue = storyboard.compute_cut(0.0, 6.0, "right", 1.0)
    assert us == 5.0 and ue == 6.0


def test_compute_cut_mid():
    us, ue = storyboard.compute_cut(0.0, 6.0, "mid", 1.0)
    assert us == 2.5 and ue == 3.5


def test_compute_cut_exceeds_duration():
    """cut > D 时只切 D"""
    us, ue = storyboard.compute_cut(0.0, 0.5, "mid", 1.0)
    assert ue - us <= 0.5


def test_snap_to_beat():
    beats = [0.5, 1.0, 1.5, 2.0]
    assert storyboard.snap_to_beat(0.55, beats) == 0.5
    assert storyboard.snap_to_beat(1.4, beats) == 1.5


def test_snap_to_beat_out_of_range():
    """偏离 > 0.3 时不吸附"""
    beats = [0.5, 1.0]
    assert storyboard.snap_to_beat(5.0, beats) == 5.0


def test_deduplicate():
    """同 main_object + action_type 去重"""
    ana = [
        AnalyzedScene(id="1", src=Path("a.mp4"), start=0, end=2, dur=2,
                      best_frame="mid", cut_duration=0.8, best_moment="a",
                      main_object="杯子", action_type="pouring"),
        AnalyzedScene(id="2", src=Path("a.mp4"), start=0, end=2, dur=2,
                      best_frame="mid", cut_duration=1.2, best_moment="b",
                      main_object="杯子", action_type="pouring"),  # 重复，但 cut 更长
        AnalyzedScene(id="3", src=Path("a.mp4"), start=0, end=2, dur=2,
                      best_frame="mid", cut_duration=0.8, best_moment="c",
                      main_object="碗", action_type="mixing"),
    ]
    kept = storyboard.deduplicate(ana)
    kept_ids = {a.id for a in kept}
    assert "2" in kept_ids  # cut 更长的保留
    assert "1" not in kept_ids
    assert "3" in kept_ids


def test_plan_basic(tmp_path):
    """plan 能生成 storyboard"""
    ana = [
        AnalyzedScene(id="1-1_0", src=Path("a.mp4"), start=0, end=2, dur=2,
                      best_frame="mid", cut_duration=0.8, best_moment="m",
                      main_object="o", action_type="pouring"),
        AnalyzedScene(id="1-2_0", src=Path("a.mp4"), start=0, end=2, dur=2,
                      best_frame="left", cut_duration=0.8, best_moment="m",
                      main_object="碗", action_type="mixing"),
    ]
    job = JobConfig(job_id="t", input_path=tmp_path)
    board = storyboard.plan(ana, job, beats=[0.5, 1.0, 1.5, 2.0])
    assert len(board.selected) == 2
    assert board.expected_duration_sec > 0
