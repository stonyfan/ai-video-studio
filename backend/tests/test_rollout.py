"""灰度命中算法单测"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.rollout import is_in_rollout, _bucket


def test_pct_zero_never_hits():
    """pct=0 → 任何 fp / release 都不命中"""
    for fp in ["a", "b", "c", "device-xyz"]:
        for rid in [1, 2, 100, 9999]:
            assert is_in_rollout(fp, rid, 0) is False


def test_pct_hundred_always_hits():
    """pct=100 → 任何 fp / release 都命中"""
    for fp in ["a", "b", "c", "device-xyz"]:
        for rid in [1, 2, 100, 9999]:
            assert is_in_rollout(fp, rid, 100) is True


def test_same_input_same_output():
    """同 (fp, release_id, pct) 100 次结果必须一致"""
    for _ in range(100):
        assert is_in_rollout("device-stable", 42, 30) is True or \
               is_in_rollout("device-stable", 42, 30) is False
    # 更严格：固定一组，比对一致性
    first = is_in_rollout("device-stable", 42, 30)
    for _ in range(100):
        assert is_in_rollout("device-stable", 42, 30) is first


def test_monotonic_subset():
    """pct=30 命中集合 ⊂ pct=60 命中集合 ⊂ pct=100 命中集合"""
    fps = [f"dev-{i:04d}" for i in range(2000)]
    release_id = 1

    hit_30 = {fp for fp in fps if is_in_rollout(fp, release_id, 30)}
    hit_60 = {fp for fp in fps if is_in_rollout(fp, release_id, 60)}
    hit_100 = {fp for fp in fps if is_in_rollout(fp, release_id, 100)}

    assert hit_30 <= hit_60, "30% 必须是 60% 的子集"
    assert hit_60 <= hit_100, "60% 必须是 100% 的子集"
    assert hit_100 == set(fps), "100% 必须命中全部"


def test_release_ids_independent():
    """不同 release_id 对同一 fp 命中独立 — 不能因为 fp 在 release 1 命中就在 release 2 也命中"""
    fps = [f"dev-{i:04d}" for i in range(2000)]
    pct = 50

    hits_r1 = {fp for fp in fps if is_in_rollout(fp, 1, pct)}
    hits_r2 = {fp for fp in fps if is_in_rollout(fp, 2, pct)}

    # 两个 release 都应接近 50% 命中率（±5%）
    assert 900 <= len(hits_r1) <= 1100, f"release 1 命中数 {len(hits_r1)} 偏离 50%"
    assert 900 <= len(hits_r2) <= 1100, f"release 2 命中数 {len(hits_r2)} 偏离 50%"

    # 命中集合应高度独立（重叠应接近 25% = 50% * 50%，允许 ±5%）
    overlap = hits_r1 & hits_r2
    assert 400 <= len(overlap) <= 600, f"重叠 {len(overlap)} 偏离预期 ~500"


def test_bucket_range():
    """bucket 必须在 0-99"""
    for fp in ["a", "b", "long-device-fp-12345"]:
        for rid in [0, 1, 99999]:
            b = _bucket(fp, rid)
            assert 0 <= b <= 99
