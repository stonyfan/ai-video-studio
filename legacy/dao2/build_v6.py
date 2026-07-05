"""
v6 step 5: 切割瞬时 + 拼接 + 加 BGM
- 读 dao2_scenes.json (src/start/end)
- 读 dao2_scenes_v6.json (best_frame/cut_duration)
- 读 dao2_storyboard_v6.json (精选顺序)
- 计算每瞬时 use_start/use_end → 切割 → concat → BGM
"""
import json
import subprocess
import sys
import sys as _sys
from pathlib import Path

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(r"C:\Users\86150\video-project")
FFMPEG = str(ROOT / "ffmpeg.exe")
SCENES_JSON = ROOT / "dao2_scenes.json"
SCENES_V6 = ROOT / "dao2_scenes_v6.json"
STORYBOARD = ROOT / "dao2_storyboard_v6.json"
CLIPS_DIR = ROOT / "_v6_clips"
CONCAT_FILE = ROOT / "concat_v6.txt"
MERGED = ROOT / "merged_v6.mp4"
BGM = ROOT / "bgm_dao2.mp3"
FINAL = ROOT / "final_dao2_v6.mp4"


def log(msg):
    print(f"[v6] {msg}", flush=True)


def compute_cut(scene, v6_data):
    """根据 best_frame 和 cut_duration 算切片位置"""
    start = scene["start"]
    end = scene["end"]
    D = end - start
    cut = min(v6_data["cut_duration"], D)
    bf = v6_data["best_frame"]

    if bf == "left":
        use_start = start
        use_end = start + cut
    elif bf == "right":
        use_start = end - cut
        use_end = end
    else:  # mid
        mid = (start + end) / 2
        use_start = max(start, mid - cut / 2)
        use_end = min(end, mid + cut / 2)
    return use_start, use_end


def cut_one(scene, v6_data, order):
    src = ROOT / scene["src"]
    use_start, use_end = compute_cut(scene, v6_data)
    out = CLIPS_DIR / f"{order:02d}_{scene['id']}.mp4"
    if out.exists() and out.stat().st_size > 3000:
        return out, use_start, use_end

    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{use_start:.3f}",
        "-to", f"{use_end:.3f}",
        "-i", src_arg,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an", "-r", "25",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-800:]
        log(f"  切失败 {scene['id']}: {err}")
        return None, use_start, use_end
    return out, use_start, use_end


def step_cut():
    CLIPS_DIR.mkdir(exist_ok=True)
    scenes = {s["id"]: s for s in json.loads(SCENES_JSON.read_text(encoding="utf-8"))["scenes"]}
    v6 = json.loads(SCENES_V6.read_text(encoding="utf-8"))["scenes"]
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    selected = sb["selected"]

    log(f"切 {len(selected)} 个瞬时")
    outs = []
    total = 0.0
    for item in selected:
        sid = item["id"]
        scene = scenes.get(sid)
        v6_data = v6.get(sid)
        if not scene or not v6_data:
            log(f"  缺数据 {sid}")
            continue
        out, us, ue = cut_one(scene, v6_data, item["order"])
        if out:
            dur = ue - us
            total += dur
            log(f"  [{item['order']:02d}] {sid} {v6_data['best_frame']} {us:.2f}-{ue:.2f} ({dur:.2f}s) - {v6_data['best_moment']}")
            outs.append(out)
    log(f"切完 {len(outs)}/{len(selected)}，总时长 {total:.2f}s")
    return outs, total


def step_concat(clips):
    clips = sorted(clips)
    CONCAT_FILE.write_text(
        "\n".join(f"file '_v6_clips/{c.name}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0",
           "-i", str(CONCAT_FILE), "-c", "copy", str(MERGED)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        sys.exit(1)
    # 取时长
    r2 = subprocess.run([FFMPEG, "-i", str(MERGED), "-f", "null", "-"],
                        capture_output=True, timeout=120)
    err = r2.stderr.decode("utf-8", errors="replace")
    import re
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
    dur = 0
    if m:
        h, mn, s = m.groups()
        dur = int(h)*3600 + int(mn)*60 + float(s)
    log(f"拼接: {MERGED.name} ({MERGED.stat().st_size/1024/1024:.1f} MB, {dur:.2f}s)")
    return dur


def step_add_bgm(video_dur):
    fade = max(0, video_dur - 1.5)
    cmd = [
        FFMPEG, "-y", "-i", str(MERGED),
        "-stream_loop", "-1", "-i", str(BGM),
        "-filter_complex",
        f"[1:a]afade=t=in:st=0:d=1.5,afade=t=out:st={fade}:d=1.5,volume=0.85[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(FINAL),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        sys.exit(1)
    log(f"成片: {FINAL.name} ({FINAL.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    outs, expected = step_cut()
    dur = step_concat(outs)
    step_add_bgm(dur)
    log(f"全部完成，预期 {expected:.1f}s，实际 {dur:.2f}s")
