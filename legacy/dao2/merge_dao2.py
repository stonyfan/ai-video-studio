"""
檀道2 视频合并流水线
- 输入：C:\\Users\\86150\\Downloads\\檀道2\\*.MP4（37 段）
- 处理：4K 横屏 → 720p 竖屏（center crop），丢音轨
- 拼接：concat demuxer
- 加 BGM：loop + 淡入淡出
- 输出：final_dao2.mp4
"""
import subprocess
import re
import sys
import json
import pickle
import sys as _sys

# Windows 控制台默认 GBK，emoji 会炸，强制 UTF-8
try:
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path

ROOT = Path(r"C:\Users\86150\video-project")
SRC = Path(r"C:\Users\86150\Downloads\檀道2")
FFMPEG = str(ROOT / "ffmpeg.exe")
CLIPS_DIR = ROOT / "clips_dao2"
ORDER_FILE = ROOT / "dao2_order.txt"
CONCAT_FILE = ROOT / "concat_dao2.txt"
BGM = ROOT / "bgm_dao2.mp3"
MERGED = ROOT / "merged_dao2.mp4"
FINAL = ROOT / "final_dao2.mp4"


def log(msg):
    print(f"[merge_dao2] {msg}", flush=True)


def get_duration(path):
    r = subprocess.run([FFMPEG, "-i", str(path), "-f", "null", "-"],
                       capture_output=True, timeout=600)
    err = r.stderr.decode("utf-8", errors="replace")
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
    if m:
        h, mn, s = m.groups()
        return int(h) * 3600 + int(mn) * 60 + float(s)
    return None


def load_order():
    """读 dao2_order.txt，取每个文件名（跳过注释和空行）"""
    names = []
    for line in ORDER_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            names.append(parts[1])
    return names


def reencode_one(src_path, out_path):
    """4K 横屏 → 720p 竖屏，丢音轨"""
    cmd = [
        FFMPEG, "-y", "-i", str(src_path),
        "-vf", "crop=1215:2160:(iw-1215)/2:0,scale=720:1280,setsar=1",
        "-r", "25",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-2000:]
        log(f"  ✗ 失败: {src_path.name}\n{err}")
        return False
    return True


def step_reencode():
    CLIPS_DIR.mkdir(exist_ok=True)
    names = load_order()
    log(f"开始重编码 {len(names)} 段")
    total_dur = 0.0
    for i, name in enumerate(names, 1):
        src = SRC / name
        out = CLIPS_DIR / f"{i:02d}.mp4"
        if not src.exists():
            log(f"  ⚠ 缺文件: {src}")
            continue
        if out.exists() and out.stat().st_size > 10000:
            log(f"  [{i:02d}/{len(names)}] 已存在，跳过: {name}")
        else:
            log(f"  [{i:02d}/{len(names)}] 重编码: {name}")
            ok = reencode_one(src, out)
            if not ok:
                continue
        d = get_duration(out)
        total_dur += d or 0
        log(f"      时长 {d:.2f}s, 累计 {total_dur:.2f}s")
    log(f"重编码完成，总时长 {total_dur:.2f}s ({total_dur/60:.1f} 分钟)")
    return total_dur


def step_concat():
    """生成 concat_dao2.txt 并拼接"""
    clips = sorted(CLIPS_DIR.glob("*.mp4"))
    CONCAT_FILE.write_text(
        "\n".join(f"file 'clips_dao2/{c.name}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    log(f"concat 列表写出 ({len(clips)} 段)")
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(CONCAT_FILE),
        "-c", "copy",
        str(MERGED),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-2000:]
        log(f"concat 失败:\n{err}")
        sys.exit(1)
    dur = get_duration(MERGED)
    log(f"拼接完成: {MERGED.name} ({MERGED.stat().st_size/1024/1024:.1f} MB, {dur:.2f}s)")
    return dur


def step_add_bgm(video_dur):
    if not BGM.exists():
        log(f"⚠ BGM 不存在: {BGM}，跳过加 BGM，输出无音视频")
        MERGED.rename(FINAL)
        return
    fade_out_start = max(0, video_dur - 2)
    cmd = [
        FFMPEG, "-y",
        "-i", str(MERGED),
        "-stream_loop", "-1", "-i", str(BGM),
        "-filter_complex",
        f"[1:a]afade=t=in:st=0:d=2,afade=t=out:st={fade_out_start}:d=2,volume=0.85[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(FINAL),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-2000:]
        log(f"加 BGM 失败:\n{err}")
        sys.exit(1)
    log(f"成片: {FINAL.name} ({FINAL.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    dur = step_reencode()
    video_dur = step_concat()
    step_add_bgm(video_dur)
    log("全部完成")
