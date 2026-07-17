"""
PyInstaller 入口：从 video_worker.__main__ 启动
（直接打 __main__.py 会丢相对 import 上下文）

最先做：把 stdout/stderr 强制改成 UTF-8。
原因：Windows 中文系统默认 cp936，Electron 那边把 stdout 字节按 UTF-8 解码 → 乱码。
env 变量 PYTHONUTF8=1 理论上也行，但放在这里更可靠（不依赖 spawn env）。
"""
import sys


def _force_utf8_stdio() -> None:
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        # Python 3.7+ TextIOWrapper 才有 reconfigure
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass


_force_utf8_stdio()

from video_worker.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
