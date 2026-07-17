"""单元测试：preprocess（旋转解析 + -vf 滤镜字符串）"""
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from video_worker.preprocess import (
    read_rotation, detect_orientation,
    build_blur_background_vf, build_normalize_vf,
)


# ===== read_rotation =====

def _make_completed(stderr_text: str):
    """构造一个 Mock 的 subprocess.CompletedProcess"""
    return MagicMock(stderr=stderr_text.encode("utf-8"), returncode=0)


def test_read_rotation_zero_no_metadata():
    """stderr 里没有 displaymatrix → 返回 0"""
    with patch("video_worker.preprocess.subprocess.run",
               return_value=_make_completed("Duration: 00:00:05.00, bitrate: 1 kb/s")):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 0


def test_read_rotation_90_cw():
    """rotation of 90 degrees → 90"""
    stderr = "Stream #0:0[0x1]: Video: hevc, 1920x1080\n        displaymatrix: rotation of 90.00 degrees"
    with patch("video_worker.preprocess.subprocess.run",
               return_value=_make_completed(stderr)):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 90


def test_read_rotation_minus_90_normalizes_to_270():
    """rotation of -90 degrees → 归一化到 270（手机竖拍典型）"""
    stderr = "        displaymatrix: rotation of -90.00 degrees"
    with patch("video_worker.preprocess.subprocess.run",
               return_value=_make_completed(stderr)):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 270


def test_read_rotation_minus_180_normalizes_to_180():
    """rotation of -180 degrees → 180"""
    stderr = "        displaymatrix: rotation of -180.00 degrees"
    with patch("video_worker.preprocess.subprocess.run",
               return_value=_make_completed(stderr)):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 180


def test_read_rotation_360_normalizes_to_0():
    """360° 应归一化到 0"""
    stderr = "        displaymatrix: rotation of 360.00 degrees"
    with patch("video_worker.preprocess.subprocess.run",
               return_value=_make_completed(stderr)):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 0


def test_read_rotation_timeout():
    """subprocess 超时 → 返回 0（不抛异常）"""
    with patch("video_worker.preprocess.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60)):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 0


def test_read_rotation_garbage_value():
    """非数字的 rotation 值 → 返回 0"""
    stderr = "        displaymatrix: rotation of abc.00 degrees"
    with patch("video_worker.preprocess.subprocess.run",
               return_value=_make_completed(stderr)):
        assert read_rotation(Path("fake.mp4"), Path("ffmpeg.exe")) == 0


# ===== build_blur_background_vf =====

def test_blur_background_vf_uses_split():
    """blur_background -vf 必须以 split 开头（关键：绕开 -filter_complex 让 autorotate 生效）"""
    vf = build_blur_background_vf((720, 1280))
    assert vf.startswith("split[a][b]")


def test_blur_background_vf_contains_bg_and_fg_chains():
    """必须包含背景模糊 + 前景缩放 + overlay 三段"""
    vf = build_blur_background_vf((720, 1280))
    assert "[bg]" in vf and "[fg]" in vf
    assert "gblur=sigma=" in vf           # 背景高斯模糊
    assert "force_original_aspect_ratio=decrease" in vf  # 前景等比缩放
    assert "overlay=" in vf                # 居中叠加


def test_blur_background_vf_resolution_in_filter():
    """目标分辨率必须出现在 filter 里"""
    vf = build_blur_background_vf((1080, 1920))
    assert "scale=1080:1920" in vf
    assert "crop=1080:1920" in vf


def test_blur_background_vf_custom_sigma():
    """自定义 sigma 必须传到 gblur"""
    vf = build_blur_background_vf((720, 1280), blur_sigma=80.0)
    assert "gblur=sigma=80.0" in vf


def test_blur_background_vf_default_sigma():
    """默认 sigma = 25.0"""
    vf = build_blur_background_vf((720, 1280))
    assert "gblur=sigma=25.0" in vf


# ===== build_normalize_vf =====

def test_normalize_vf_vertical_simple_scale():
    """竖屏 → 直接 scale，不管 strategy"""
    vf = build_normalize_vf((720, 1280), "vertical", "blur_background")
    assert vf == "scale=720:1280:flags=lanczos"


def test_normalize_vf_vertical_ignores_strategy():
    """竖屏 + 任何 strategy 都走 simple scale"""
    for strategy in ["crop", "letterbox", "blur_background"]:
        vf = build_normalize_vf((720, 1280), "vertical", strategy)  # type: ignore[arg-type]
        assert vf == "scale=720:1280:flags=lanczos"


def test_normalize_vf_horizontal_blur_background():
    """横屏 + blur_background → 用 split 链（关键：不能走 -filter_complex）"""
    vf = build_normalize_vf((720, 1280), "horizontal", "blur_background")
    assert vf.startswith("split[a][b]")
    assert "gblur=sigma=25.0" in vf


def test_normalize_vf_horizontal_crop():
    """横屏 + crop → 中央裁切 + scale"""
    vf = build_normalize_vf((720, 1280), "horizontal", "crop")
    assert vf == "crop=ih*9/16:ih,scale=720:1280:flags=lanczos"


def test_normalize_vf_horizontal_letterbox():
    """横屏 + letterbox → scale + pad"""
    vf = build_normalize_vf((720, 1280), "horizontal", "letterbox")
    assert vf == "scale=720:-1,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black"


def test_normalize_vf_unknown_strategy_fallback():
    """未知 strategy → simple scale"""
    vf = build_normalize_vf((720, 1280), "horizontal", "weird_strategy")  # type: ignore[arg-type]
    assert vf == "scale=720:1280:flags=lanczos"


def test_normalize_vf_unknown_orientation_treated_as_vertical():
    """未知 orientation（如 detect_orientation 失败）→ 当竖屏处理（保守）"""
    vf = build_normalize_vf((720, 1280), "unknown", "blur_background")
    assert vf == "scale=720:1280:flags=lanczos"


# ===== 集成测试（需要 ffmpeg + dunhuang_mini 样本）=====

SAMPLES_DIR = Path("D:/ai-video-studio/samples/dunhuang_mini")
FFMPEG = Path("D:/ai-video-studio/tools/ffmpeg.exe")

# 期望值：基于实际 dunhuang_mini 样本的 ffmpeg -i 输出
SAMPLE_ROTATIONS = {
    "2024-07-02 230830.mov": 0,    # 无旋转
    "2024-07-03 122502.mov": 180,  # 拍倒了
    "2024-07-03 142519.mov": 270,  # 手机竖拍（-90° 归一化）
    "2024-07-03 142611.mov": 270,  # 同上
}
SAMPLE_ORIENTATIONS = {
    "2024-07-02 230830.mov": "horizontal",   # 3840x2160 横拍
    "2024-07-03 142519.mov": "vertical",     # 3840x2160 + -90° → 显示为 2160x3840 竖
}


def _samples_available() -> bool:
    return SAMPLES_DIR.is_dir() and FFMPEG.exists() and any(SAMPLES_DIR.glob("*.mov"))


pytestmark = pytest.mark.skipif(
    not _samples_available(),
    reason=f"需要 dunhuang_mini 样本 + ffmpeg.exe（找 {SAMPLES_DIR}）"
)


@pytest.mark.parametrize("clip_name,expected_rot", list(SAMPLE_ROTATIONS.items()))
def test_read_rotation_real_clips(clip_name: str, expected_rot: int):
    """对真实素材跑 read_rotation，验证归一化结果"""
    rot = read_rotation(SAMPLES_DIR / clip_name, FFMPEG)
    assert rot == expected_rot


@pytest.mark.parametrize("clip_name,expected_orient", list(SAMPLE_ORIENTATIONS.items()))
def test_detect_orientation_with_rotation(clip_name: str, expected_orient: str):
    """detect_orientation 必须考虑 autorotate（-90° 的 clip 应判为 vertical）"""
    orient = detect_orientation(SAMPLES_DIR / clip_name, FFMPEG)
    assert orient == expected_orient
