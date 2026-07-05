"""
yulan step 1: 标准化素材
- 输入：D:\BaiduNetdiskDownload\玉兰花马天尼\*.MP4（19 段 4K 竖屏）
- 输出：clips/<name>.mp4（720×1280 9:16 H264 25fps，去音轨）
"""
import subprocess
import sys
import sys as _sys
from pathlib import Path

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
PARENT = ROOT.parent
FFMPEG = str(PARENT / "ffmpeg.exe")
SRC_DIR = Path(r"D:\BaiduNetdiskDownload\玉兰花马天尼")
CLIPS_DIR = ROOT / "clips"


def log(msg):
    print(f"[prep] {msg}", flush=True)


def normalize(src, out):
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    # 4K 2160x3840 → 720x1280 直接 scale（已经是 9:16）
    cmd = [
        FFMPEG, "-y", "-i", src_arg,
        "-vf", "scale=720:1280:flags=lanczos",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", "-r", "25",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    return r.returncode == 0


def main():
    CLIPS_DIR.mkdir(exist_ok=True)
    srcs = sorted(SRC_DIR.glob("*.MP4"))
    log(f"待处理 {len(srcs)} 段")
    cnt = 0
    for src in srcs:
        out = CLIPS_DIR / f"{src.stem}.mp4"
        if out.exists() and out.stat().st_size > 100000:
            cnt += 1
            log(f"  [{src.stem}] 已存在，跳过")
            continue
        ok = normalize(src, out)
        if ok:
            cnt += 1
            log(f"  [{src.stem}] OK ({out.stat().st_size//1024} KB)")
        else:
            log(f"  [{src.stem}] FAILED")
    log(f"完成 {cnt}/{len(srcs)}")


if __name__ == "__main__":
    main()
