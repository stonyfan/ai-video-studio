"""
yulan 多平台版本构建器（每平台独立 BGM + 节拍对齐）
- 抖音 15s：Sudden Tour 172 BPM 极限快剪（冷调 + 大字）
- 小红书 30s：slow down 86 BPM 暖调氛围（细字）
- 视频号 30s：Dubstepper 95 BPM 自然色调（中速）
"""
import json
import subprocess
import sys
import sys as _sys
import argparse
from pathlib import Path

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
PARENT = ROOT.parent
FFMPEG = str(PARENT / "ffmpeg.exe")

SCENES_JSON = ROOT / "scenes.json"
SCENES_V6 = ROOT / "scenes_v6.json"


PLATFORM_CONFIG = {
    "douyin15": {
        "storyboard": "storyboard_douyin15.json",
        "output": "final_玉兰马天尼_抖音15s.mp4",
        "bgm": "bgm_pool/Sudden Tour.mp3",
        "atempo": 1.5,  # 85 → 127 BPM（快节奏）
        "grade": (
            "eq=saturation=0.80,"
            "colorbalance=bs=0.25:bm=0.15:bh=-0.08,"
            "curves=preset=increase_contrast,"
            "unsharp=5:5:1.0:5:5:0,"
            "eq=brightness=0.04:saturation=1.12"
        ),
        "ass_fontsize": 36, "ass_outline": 3.5, "ass_marginv": 100,
    },
    "xhs30": {
        "storyboard": "storyboard_xhs30.json",
        "output": "final_玉兰马天尼_小红书30s.mp4",
        "bgm": "bgm_pool/slow down.mp3",
        "atempo": 0.85,  # 85 → 72 BPM（更慢更治愈）
        "grade": (
            "eq=saturation=0.92,"
            "colorbalance=rs=0.12:rm=0.10:rh=0.05:gs=0.03:gm=0.02,"
            "curves=preset=lighter,"
            "unsharp=3:3:0.4:3:3:0,"
            "eq=brightness=0.05:saturation=0.95:gamma=0.95"
        ),
        "ass_fontsize": 26, "ass_outline": 1.5, "ass_marginv": 90,
    },
    "videohao30": {
        "storyboard": "storyboard_videohao30.json",
        "output": "final_玉兰马天尼_视频号30s.mp4",
        "bgm": "bgm.mp3",
        "atempo": 1.0,  # 95 BPM 原速
        "grade": (
            "eq=saturation=0.95,"
            "colorbalance=bs=0.08:bm=0.04,"
            "curves=preset=increase_contrast,"
            "unsharp=3:3:0.5:3:3:0,"
            "eq=brightness=0.02:saturation=1.0"
        ),
        "ass_fontsize": 30, "ass_outline": 2.5, "ass_marginv": 110,
    },
}


def log(msg):
    print(f"[build] {msg}", flush=True)


def load_beats(bgm_path):
    import librosa
    y, sr = librosa.load(str(bgm_path), duration=60)
    result = librosa.beat.beat_track(y=y, sr=sr)
    beats_frames = result[1] if isinstance(result, tuple) and len(result) > 1 else None
    if beats_frames is None or len(beats_frames) == 0:
        return []
    return librosa.frames_to_time(beats_frames, sr=sr).tolist()


def snap(t, beats, max_adj=0.3):
    if not beats:
        return t
    nearest = min(beats, key=lambda b: abs(b - t))
    return nearest if abs(nearest - t) <= max_adj else t


def compute_cut(scene, v6_data, override_dur):
    start, end = scene["start"], scene["end"]
    D = end - start
    cut = min(override_dur, D)
    bf = v6_data["best_frame"]
    if bf == "left":
        return start, start + cut
    elif bf == "right":
        return end - cut, end
    else:
        mid = (start + end) / 2
        return max(start, mid - cut/2), min(end, mid + cut/2)


def cut_one(item, scene, v6_data, beats, grade_filter, clips_dir):
    """按 cut_duration 切，us/ue 吸附到最近节拍"""
    us, ue = compute_cut(scene, v6_data, item.get("cut_duration", 1.0))
    us = snap(us, beats, 0.30)
    ue = snap(ue, beats, 0.30)
    if ue <= us + 0.3:
        ue = us + 0.5

    out = clips_dir / f"{item['order']:02d}_{item['id']}.mp4"
    if out.exists() and out.stat().st_size > 5000:
        return out, us, ue

    src_arg = str(ROOT / scene["src"]).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{us:.3f}", "-to", f"{ue:.3f}",
        "-i", src_arg,
        "-vf", grade_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", "-r", "25",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        return None, us, ue
    return out, us, ue


def write_ass(timeline, cfg, ass_path):
    items = [(t["t_start"], t["t_end"], t["subtitle"])
             for t in timeline if t["subtitle"]]
    if not items:
        return None

    def fmt(s):
        h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
        cs = int((sec - int(sec)) * 100)
        return f"{h:d}:{m:02d}:{int(sec):02d}.{cs:02d}"

    fs, ol, mv = cfg["ass_fontsize"], cfg["ass_outline"], cfg["ass_marginv"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,{ol},1,2,40,40,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in items:
        lines.append(f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{text}")
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def build_platform(platform):
    cfg = PLATFORM_CONFIG[platform]
    bgm_path = ROOT / cfg["bgm"]
    log(f"=== 构建 {platform} ===")
    log(f"BGM={cfg['bgm']}  output={cfg['output']}")

    # 加载该 BGM 的节拍，按 atempo 缩放节拍时间
    beats = load_beats(bgm_path)
    atempo = cfg.get("atempo", 1.0)
    if atempo != 1.0 and beats:
        beats = [b / atempo for b in beats]
    if beats:
        avg = sum(b2-b1 for b1, b2 in zip(beats[:-1], beats[1:])) / (len(beats)-1)
        log(f"节拍: {len(beats)} 拍, atempo={atempo}, 间距 {avg:.3f}s (BPM ~{60/avg:.0f})")

    scenes = json.loads(SCENES_JSON.read_text(encoding="utf-8"))
    scenes = {sid: s for sid, s in scenes.items()}
    v6 = json.loads(SCENES_V6.read_text(encoding="utf-8"))["scenes"]
    sb = json.loads((ROOT / cfg["storyboard"]).read_text(encoding="utf-8"))

    clips_dir = ROOT / f"_clips_{platform}"
    clips_dir.mkdir(exist_ok=True)
    concat_file = ROOT / f"concat_{platform}.txt"
    merged = ROOT / f"merged_{platform}.mp4"
    final = ROOT / cfg["output"]

    log(f"切 {len(sb['selected'])} 个瞬时")
    outs, timeline, total = [], [], 0.0
    for item in sb["selected"]:
        sid = item["id"]
        if sid not in scenes or sid not in v6:
            continue
        out, us, ue = cut_one(item, scenes[sid], v6[sid], beats,
                             cfg["grade"], clips_dir)
        if out:
            dur = ue - us
            timeline.append({"order": item["order"], "id": sid,
                             "t_start": total, "t_end": total + dur,
                             "duration": dur, "subtitle": item.get("subtitle")})
            total += dur
            outs.append(out)
    log(f"切完 {len(outs)} 个，总时长 {total:.2f}s")

    outs = sorted(outs)
    concat_file.write_text(
        "\n".join(f"file '{clips_dir.name}/{c.name}'" for c in outs) + "\n",
        encoding="utf-8",
    )
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0",
                    "-i", str(concat_file), "-c", "copy", str(merged)],
                   capture_output=True, timeout=300)

    ass_path = ROOT / f"subtitles_{platform}.ass"
    srt = write_ass(timeline, cfg, ass_path)
    fade_out = max(0, total - 1.5)

    cmd = [FFMPEG, "-y", "-i", str(merged), "-stream_loop", "-1", "-i", str(bgm_path)]
    if srt:
        cmd += ["-vf", f"subtitles='{srt.name}'"]
    audio_chain = f"atempo={atempo},volume=0.85,afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out}:d=1.5"
    cmd += [
        "-filter_complex",
        f"[1:a]{audio_chain}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(final),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(ROOT))
    if r.returncode == 0 and final.exists():
        log(f"完成: {final.name} ({final.stat().st_size/1024/1024:.1f} MB)")
    else:
        err = r.stderr.decode("utf-8", errors="replace")[-1000:]
        log(f"失败: {err}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=list(PLATFORM_CONFIG.keys()))
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.all:
        for p in PLATFORM_CONFIG:
            build_platform(p)
    elif args.platform:
        build_platform(args.platform)
    else:
        parser.print_help()
