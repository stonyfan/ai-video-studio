"""
路径解析（dev / PyInstaller frozen 双模式）

PyInstaller --onedir 模式下：
  sys.executable      = dist/video-worker/video-worker.exe
  sys._MEIPASS        = dist/video-worker/_internal/   (bundled 数据文件根)

bundled 资源路径：
  configs/             → <_internal>/configs/
  tools/ffmpeg.exe     → <_internal>/tools/ffmpeg.exe

dev 模式（python -m video_worker）下：
  __file__             = video_worker/paths.py
  project root         = Path(__file__).parent.parent
"""
from __future__ import annotations
import sys
from pathlib import Path


def is_frozen() -> bool:
    return getattr(sys, 'frozen', False)


def bundle_root() -> Path:
    """bundled 资源根目录（dev 模式下返回 project root）"""
    if is_frozen():
        # PyInstaller 设的 _MEIPASS 指向 _internal/
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            return Path(meipass)
        # fallback：sys.executable 同级（理论上 onedir 不会走到这里）
        return Path(sys.executable).parent
    # dev：video_worker/paths.py → 上两级是 project root
    return Path(__file__).resolve().parent.parent


def bundled_ffmpeg() -> Path:
    """bundled ffmpeg.exe 路径"""
    return bundle_root() / 'tools' / 'ffmpeg.exe'


def resolve_ffmpeg(ffmpeg_arg: Path | None) -> Path:
    """
    优先用调用方显式传入的 --ffmpeg；
    若不存在（相对路径在当前 CWD 找不到），fallback 到 bundled ffmpeg。
    """
    if ffmpeg_arg and ffmpeg_arg.exists():
        return ffmpeg_arg
    bundled = bundled_ffmpeg()
    if bundled.exists():
        return bundled
    # 都找不到就返回原 arg，让下游 subprocess 报错时路径至少有意义
    return ffmpeg_arg or bundled


def bundled_config(config_arg: Path | None) -> Path:
    """配置文件路径解析"""
    if config_arg and config_arg.exists():
        return config_arg
    return bundle_root() / 'configs' / 'default.yaml'
