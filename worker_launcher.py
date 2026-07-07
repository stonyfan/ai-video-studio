"""
PyInstaller 入口：从 video_worker.__main__ 启动
（直接打 __main__.py 会丢相对 import 上下文）
"""
from video_worker.__main__ import main

if __name__ == "__main__":
    main()
