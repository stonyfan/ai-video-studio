"""
yulan 最终 build：
- 切每瞬时（含冷调 + 高光增强滤镜）
- concat 拼接
- 烧入 SRT 字幕
- 加 BGM（淡入淡出）
"""
import json
import subprocess
import sys
import sys as _sys
import re
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
STORYBOARD = ROOT / "storyboard.json"
BEATS_JSON = ROOT / "beats.json"

CLIPS_DIR = ROOT / "_v7_clips"
CONCAT_FILE = ROOT / "concat_v7.txt"
MERGED = ROOT / "merged_v7.mp4"
BGM = ROOT / "bgm.mp3"
FINAL = ROOT / "final_玉兰马天尼.mp4"

# 冷调 + 高光增强 + 酒液气泡锐化
GRADE_FILTER = (
    "eq=saturation=0.85,"
    "colorbalance=bs=0.18:bm=0.10:bh=-0.05,"
    "curves=preset=increase_contrast,"
    "unsharp=3:3:0.6:3:3:0,"
    "eq=brightness=0.03:saturation=1.08"
)


def log(msg):
    print(f"[v7] {msg}", flush=True)


def load_data():
    scenes = {s["id"]: s for s in json.loads(SCENES_JSON.read_text(encoding="utf-8")).values()}
    v6 = json.loads(SCENES_V6.read_text(encoding="utf-8"))["scenes"]
    sb = json.loads(STORYBOARD.read_text(encoding="utf-8"))
    beats = json.loads(BEATS_JSON.read_text(encoding="utf-8"))["beat_times"]
    return scenes, v6, sb, beats


def snap_to_beat(t, beats, max_adj=0.3):
    """把时间戳吸附到最近 beat（节拍对齐）"""
    nearest = min(beats, key=lambda b: abs(b - t))
    if abs(nearest - t) <= max_adj:
        return nearest
    return t


def compute_cut(scene, v6_data, override_dur=None):
    start = scene["start"]
    end = scene["end"]
    D = end - start
    cut = override_dur if override_dur else v6_data["cut_duration"]
    cut = min(cut, D)
    bf = v6_data["best_frame"]
    if bf == "left":
        us, ue = start, start + cut
    elif bf == "right":
        us, ue = end - cut, end
    else:
        mid = (start + end) / 2
        us = max(start, mid - cut / 2)
        ue = min(end, mid + cut / 2)
    return us, ue


def cut_one(item, scene, v6_data, beats):
    """切单瞬时 + 应用冷调/高光滤镜"""
    us, ue = compute_cut(scene, v6_data, item.get("cut_duration"))
    # 节拍对齐：ue 吸附到最近 beat
    us_snapped = snap_to_beat(us, beats, max_adj=0.25)
    ue_snapped = snap_to_beat(ue, beats, max_adj=0.25)
    if ue_snapped <= us_snapped:
        ue_snapped = us_snapped + (ue - us)

    out = CLIPS_DIR / f"{item['order']:02d}_{item['id']}.mp4"
    if out.exists() and out.stat().st_size > 5000:
        return out, us_snapped, ue_snapped

    src = ROOT / scene["src"]
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [
        FFMPEG, "-y",
        "-ss", f"{us_snapped:.3f}",
        "-to", f"{ue_snapped:.3f}",
        "-i", src_arg,
        "-vf", GRADE_FILTER,
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", "-r", "25",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        log(f"  切失败 {item['id']}: {err}")
        return None, us_snapped, ue_snapped
    return out, us_snapped, ue_snapped


def step_cut(scenes, v6, sb, beats):
    CLIPS_DIR.mkdir(exist_ok=True)
    log(f"切 {len(sb['selected'])} 个瞬时（含冷调+高光）")
    outs = []
    timeline = []
    total = 0.0
    for item in sb["selected"]:
        sid = item["id"]
        scene = scenes.get(sid)
        v6_data = v6.get(sid)
        if not scene or not v6_data:
            continue
        out, us, ue = cut_one(item, scene, v6_data, beats)
        if out:
            dur = ue - us
            timeline.append({"order": item["order"], "id": sid,
                             "t_start": total, "t_end": total + dur,
                             "duration": dur, "subtitle": item.get("subtitle")})
            total += dur
            outs.append(out)
            log(f"  [{item['order']:02d}] {sid} {v6_data['best_frame']} {us:.2f}-{ue:.2f} ({dur:.2f}s) {v6_data['best_moment']}")
    log(f"切完 {len(outs)} 个，总时长 {total:.2f}s")
    return outs, timeline, total


def step_concat(clips):
    clips = sorted(clips)
    CONCAT_FILE.write_text(
        "\n".join(f"file '_v7_clips/{c.name}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [FFMPEG, "-y", "-f", "concat", "-safe", "0",
           "-i", str(CONCAT_FILE), "-c", "copy", str(MERGED)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    return r.returncode == 0


def write_srt(timeline):
    """根据 timeline + storyboard 的 subtitle 字段生成 ASS 字幕（抖音风大字）"""
    items = []
    for t in timeline:
        if t["subtitle"]:
            items.append((t["t_start"], t["t_end"], t["subtitle"]))

    if not items:
        return None

    def fmt_ass_time(s):
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        sec = s % 60
        cs = int((sec - int(sec)) * 100)
        return f"{h:d}:{m:02d}:{int(sec):02d}.{cs:02d}"

    # ASS 头部：微软雅黑 24pt 白字黑描边，居中下方
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,30,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2.5,1,2,40,40,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in items:
        lines.append(
            f"Dialogue: 0,{fmt_ass_time(start)},{fmt_ass_time(end)},Default,,0,0,0,,{text}"
        )
    ass_path = ROOT / "subtitles.ass"
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def step_subtitle_and_bgm(timeline, total_dur):
    """合并：把字幕烧入 merged + 加 BGM"""
    srt = write_srt(timeline)
    fade_out_start = max(0, total_dur - 1.5)

    cmd = [
        FFMPEG, "-y",
        "-i", str(MERGED),
        "-stream_loop", "-1", "-i", str(BGM),
    ]
    # 视频滤镜：字幕烧入（ASS）
    vf = f"subtitles='{srt.name}'" if srt else None
    # 音频滤镜：BGM 音量 + 淡入淡出
    af = f"volume=0.85,afade=t=in:st=0:d=1.0,afade=t=out:st={fade_out_start}:d=1.5"

    cmd += ["-vf", vf] if vf else []
    cmd += ["-filter_complex", f"[1:a]{af}[a]", "-map", "0:v", "-map", "[a]"]
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(FINAL),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(ROOT))
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"渲染失败: {err}")
        return False
    return True


if __name__ == "__main__":
    scenes, v6, sb, beats = load_data()
    log(f"BPM={int(60000/max([b for b in beats if b>0][:5]))} 节拍间距 ~{beats[1]-beats[0]:.3f}s" if len(beats)>1 else "no beats")
    outs, timeline, total = step_cut(scenes, v6, sb, beats)
    ok = step_concat(outs)
    if not ok:
        sys.exit(1)
    log(f"拼接完成 {MERGED.name}")
    ok = step_subtitle_and_bgm(timeline, total)
    if ok:
        log(f"成片: {FINAL.name} ({FINAL.stat().st_size/1024/1024:.1f} MB)")
        log(f"总时长: {total:.2f}s")
