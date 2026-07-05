"""
檀道2 第五阶段 step 5: 按 storyboard 切场景 + 拼接 + 加 BGM
- 输入：clips_dao2_v4/*.mp4 + dao2_storyboard.json + bgm_dao2.mp3
- 输出：final_dao2_v5.mp4
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
STORYBOARD = ROOT / "dao2_storyboard.json"
SCENES_JSON = ROOT / "dao2_scenes.json"
CLIPS_DIR = ROOT / "_v5_clips"
CONCAT_FILE = ROOT / "concat_v5.txt"
MERGED = ROOT / "merged_v5.mp4"
BGM = ROOT / "bgm_dao2.mp3"
FINAL = ROOT / "final_dao2_v5.mp4"


def log(msg):
    print(f"[v5] {msg}", flush=True)


def load_scene_src_map():
    """从 dao2_scenes.json 构建 {scene_id: src_path} 映射"""
    d = json.loads(SCENES_JSON.read_text(encoding="utf-8"))
    return {s["id"]: s["src"] for s in d["scenes"]}


def cut_scene(scene, src_map):
    """从源视频切出指定时间段（重编码，精确切）"""
    src_rel = src_map.get(scene["id"])
    if not src_rel:
        log(f"  缺 src for {scene['id']}")
        return None
    src = ROOT / src_rel
    out = CLIPS_DIR / f"{scene['order']:02d}_{scene['id']}.mp4"
    if out.exists() and out.stat().st_size > 5000:
        log(f"  [{scene['order']}] 已存在 {out.name}")
        return out

    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [
        FFMPEG, "-y",
        "-ss", str(scene["use_start"]),
        "-to", str(scene["use_end"]),
        "-i", src_arg,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",  # 已经无音轨，重复指定
        "-r", "25",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-1000:]
        log(f"  失败 {scene['id']}: {err}")
        return None
    log(f"  [{scene['order']}] 切出 {out.name} ({out.stat().st_size//1024} KB)")
    return out


def step_cut():
    CLIPS_DIR.mkdir(exist_ok=True)
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    selected = sb["selected"]
    src_map = load_scene_src_map()
    log(f"切 {len(selected)} 个场景")
    outs = []
    for sc in selected:
        out = cut_scene(sc, src_map)
        if out:
            outs.append(out)
    log(f"切完 {len(outs)}/{len(selected)}")
    return outs


def step_concat(clips):
    # 按文件名排序保证顺序
    clips = sorted(clips)
    CONCAT_FILE.write_text(
        "\n".join(f"file '_v5_clips/{c.name}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [
        FFMPEG, "-y", "-f", "concat", "-safe", "0",
        "-i", str(CONCAT_FILE), "-c", "copy", str(MERGED),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-1000:]
        log(f"concat 失败: {err}")
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
        err = r.stderr.decode("utf-8", errors="replace")[-1000:]
        log(f"加 BGM 失败: {err}")
        sys.exit(1)
    log(f"成片: {FINAL.name} ({FINAL.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    clips = step_cut()
    dur = step_concat(clips)
    step_add_bgm(dur)
    log(f"全部完成，成片时长 {dur:.1f}s")
