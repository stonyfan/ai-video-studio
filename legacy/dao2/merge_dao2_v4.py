"""
檀道2 第四阶段：修正方向错误
- 源实际是 2160×3840 竖屏（不是 3840×2160 横屏），无需 crop
- 直接 scale 到 720×1280
- 加 vidstab 稳定 + BGM
"""
import subprocess
import re
import sys
import sys as _sys

try:
    _sys.stdout.reconfigure(encoding="utf-8")
    _sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from pathlib import Path

ROOT = Path(r"C:\Users\86150\video-project")
SRC = Path(r"C:\Users\86150\Downloads\檀道2")
FFMPEG = str(ROOT / "ffmpeg.exe")

CLIPS_V4 = ROOT / "clips_dao2_v4"
TRF_V4 = ROOT / "trf_v4"
CLIPS_V4_STAB = ROOT / "clips_dao2_v4_stab"
CONCAT_FILE = ROOT / "concat_dao2_v4.txt"
MERGED = ROOT / "merged_dao2_v4.mp4"
BGM = ROOT / "bgm_dao2.mp3"
FINAL = ROOT / "final_dao2_v4.mp4"
ORDER_FILE = ROOT / "dao2_order.txt"

SHAKINESS = 5
ACCURACY = 10
SMOOTHING = 30
ZOOM = 5


def log(msg):
    print(f"[v4] {msg}", flush=True)


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
    order = []
    for line in ORDER_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            order.append((parts[0], parts[1]))
    return order


def reencode_one(src_path, out_path):
    """源 2160x3840 竖屏 → 720x1280（无 crop，只 scale）"""
    src_arg = str(src_path).replace("\\", "/")
    out_arg = str(out_path).replace("\\", "/")
    cmd = [
        FFMPEG, "-y", "-i", src_arg,
        "-vf", "scale=720:1280,setsar=1",
        "-r", "25",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"  失败: {src_path.name}\n{err}")
        return False
    return True


def stabilize_one(src, trf_path, out_path):
    src_arg = src.relative_to(ROOT).as_posix()
    trf_arg = trf_path.relative_to(ROOT).as_posix()
    out_arg = out_path.relative_to(ROOT).as_posix()

    detect_cmd = [
        FFMPEG, "-y", "-i", src_arg,
        "-vf", f"vidstabdetect=shakiness={SHAKINESS}:accuracy={ACCURACY}:result={trf_arg}",
        "-f", "null", "-",
    ]
    r1 = subprocess.run(detect_cmd, capture_output=True, timeout=600, cwd=str(ROOT))
    if r1.returncode != 0 or not trf_path.exists():
        log(f"  detect 失败: {src.name}")
        return False

    transform_cmd = [
        FFMPEG, "-y", "-i", src_arg,
        "-vf",
        f"vidstabtransform=input={trf_arg}:smoothing={SMOOTHING}:zoom={ZOOM}:optzoom=1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an", "-r", "25",
        out_arg,
    ]
    r2 = subprocess.run(transform_cmd, capture_output=True, timeout=900, cwd=str(ROOT))
    return r2.returncode == 0


def step_reencode():
    CLIPS_V4.mkdir(exist_ok=True)
    order = load_order()
    log(f"重编码 {len(order)} 段（无 crop）")
    for idx, name in order:
        src = SRC / name
        out = CLIPS_V4 / f"{idx}.mp4"
        if not src.exists():
            continue
        if out.exists() and out.stat().st_size > 10000:
            log(f"  [{idx}] 跳过 {name}")
            continue
        log(f"  [{idx}] {name}")
        reencode_one(src, out)
    total = sum(get_duration(p) or 0 for p in CLIPS_V4.glob("*.mp4"))
    log(f"重编码完成，总时长 {total:.2f}s ({total/60:.1f} 分钟)")


def step_stabilize():
    TRF_V4.mkdir(exist_ok=True)
    CLIPS_V4_STAB.mkdir(exist_ok=True)
    clips = sorted(CLIPS_V4.glob("*.mp4"))
    log(f"稳定 {len(clips)} 段")
    success = 0
    for clip in clips:
        name = clip.stem
        trf = TRF_V4 / f"{name}.trf"
        out = CLIPS_V4_STAB / f"{name}.mp4"
        if out.exists() and out.stat().st_size > 10000 and trf.exists():
            log(f"  [{name}] 跳过")
            success += 1
            continue
        log(f"  [{name}] 稳定中...")
        ok = stabilize_one(clip, trf, out)
        if ok:
            success += 1
        else:
            import shutil
            shutil.copy2(clip, out)
    log(f"稳定完成: {success}/{len(clips)}")


def step_concat():
    clips = sorted(CLIPS_V4_STAB.glob("*.mp4"))
    CONCAT_FILE.write_text(
        "\n".join(f"file 'clips_dao2_v4_stab/{c.name}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0",
           "-i", str(CONCAT_FILE), "-c", "copy", str(MERGED)]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        sys.exit(1)
    dur = get_duration(MERGED)
    log(f"拼接: {MERGED.name} ({MERGED.stat().st_size/1024/1024:.1f} MB, {dur:.2f}s)")
    return dur


def step_add_bgm(video_dur):
    if not BGM.exists():
        MERGED.rename(FINAL)
        return
    fade = max(0, video_dur - 2)
    cmd = [
        FFMPEG, "-y", "-i", str(MERGED),
        "-stream_loop", "-1", "-i", str(BGM),
        "-filter_complex",
        f"[1:a]afade=t=in:st=0:d=2,afade=t=out:st={fade}:d=2,volume=0.85[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(FINAL),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0:
        sys.exit(1)
    log(f"成片: {FINAL.name} ({FINAL.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    step_reencode()
    step_stabilize()
    dur = step_concat()
    step_add_bgm(dur)
    log("全部完成")
