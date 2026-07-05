"""
渲染：FFmpeg 切片 + 节拍对齐 + 色调 + 字幕 + BGM
"""
from __future__ import annotations
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional

from .validators import JobConfig, Storyboard, AnalyzedScene


# 色调预设（参考 legacy/yulan/multi_build.py PLATFORM_CONFIG）
COLOR_GRADES = {
    "cool_strong": (
        "eq=saturation=0.80,"
        "colorbalance=bs=0.25:bm=0.15:bh=-0.08,"
        "curves=preset=increase_contrast,"
        "unsharp=5:5:1.0:5:5:0,"
        "eq=brightness=0.04:saturation=1.12"
    ),
    "warm": (
        "eq=saturation=0.92,"
        "colorbalance=rs=0.12:rm=0.10:rh=0.05:gs=0.03:gm=0.02,"
        "curves=preset=lighter,"
        "unsharp=3:3:0.4:3:3:0,"
        "eq=brightness=0.05:saturation=0.95:gamma=0.95"
    ),
    "natural": (
        "eq=saturation=0.95,"
        "colorbalance=bs=0.08:bm=0.04,"
        "curves=preset=increase_contrast,"
        "unsharp=3:3:0.5:3:3:0,"
        "eq=brightness=0.02:saturation=1.0"
    ),
}


def cut_clip(src: Path, us: float, ue: float, out: Path,
             ffmpeg_path: Path, grade_filter: str,
             crf: int = 20, logger: Optional[logging.Logger] = None) -> bool:
    """切单段，应用色调滤镜"""
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [
        str(ffmpeg_path), "-y",
        "-ss", f"{us:.3f}", "-to", f"{ue:.3f}",
        "-i", src_arg,
        "-vf", grade_filter,
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an", "-r", "25",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    ok = r.returncode == 0 and out.exists() and out.stat().st_size > 5000
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"切片失败 {src.name}: {err}")
    return ok


def concat(clips: list[Path], concat_file: Path, output: Path,
           ffmpeg_path: Path, logger: Optional[logging.Logger] = None) -> bool:
    """concat demuxer"""
    clips = sorted(clips)
    concat_file.write_text(
        "\n".join(f"file '{c.parent.name}/{c.name}'" for c in clips) + "\n",
        encoding="utf-8",
    )
    cmd = [str(ffmpeg_path), "-y", "-f", "concat", "-safe", "0",
           "-i", str(concat_file), "-c", "copy", str(output)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    ok = r.returncode == 0
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"concat 失败: {err}")
    return ok


def write_ass(timeline: list[dict], ass_path: Path,
              fontsize: int = 30, outline: float = 2.5, marginv: int = 100) -> Optional[Path]:
    items = [(t["t_start"], t["t_end"], t["subtitle"])
             for t in timeline if t.get("subtitle")]
    if not items:
        return None

    def fmt(s: float) -> str:
        h = int(s // 3600); m = int((s % 3600) // 60); sec = s % 60
        cs = int((sec - int(sec)) * 100)
        return f"{h:d}:{m:02d}:{int(sec):02d}.{cs:02d}"

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{fontsize},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,1,0,1,{outline},1,2,40,40,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in items:
        lines.append(f"Dialogue: 0,{fmt(start)},{fmt(end)},Default,,0,0,0,,{text}")
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def add_bgm_and_subtitles(merged: Path, bgm: Path, output: Path,
                          ass_path: Optional[Path], ffmpeg_path: Path,
                          atempo: float = 1.0, bgm_volume: float = 0.85,
                          fade_in: float = 1.0, fade_out: float = 1.5,
                          total_dur: float = 0.0,
                          crf: int = 20, logger: Optional[logging.Logger] = None) -> bool:
    cmd = [str(ffmpeg_path), "-y", "-i", str(merged),
           "-stream_loop", "-1", "-i", str(bgm)]
    if ass_path:
        cmd += ["-vf", f"subtitles='{ass_path.name}'"]
    fade_out_start = max(0, total_dur - fade_out)
    audio_chain = f"atempo={atempo},volume={bgm_volume},afade=t=in:st=0:d={fade_in},afade=t=out:st={fade_out_start}:d={fade_out}"
    cmd += [
        "-filter_complex", f"[1:a]{audio_chain}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(output),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    ok = r.returncode == 0
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-1000:]
        logger.error(f"BGM/字幕烧入失败: {err}")
    return ok


def render(board: Storyboard, analyzed: list[AnalyzedScene],
           config: JobConfig, job_dir: Path,
           color_grade: str = "natural",
           bgm_atempo: float = 1.0,
           ass_fontsize: int = 30,
           ass_outline: float = 2.5,
           ass_marginv: int = 100,
           crf: int = 20,
           bgm_volume: float = 0.85,
           fade_in: float = 1.0,
           fade_out: float = 1.5,
           logger: Optional[logging.Logger] = None) -> Path:
    """主渲染：切每段 → concat → 字幕+BGM"""
    clips_dir = job_dir / "work" / "final_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    concat_file = job_dir / "work" / "concat.txt"
    merged = job_dir / "work" / "merged.mp4"
    ass_path = job_dir / "work" / "subtitles.ass"
    output = job_dir / "output" / "final.mp4"

    grade_filter = COLOR_GRADES.get(color_grade, COLOR_GRADES["natural"])

    # analyzed 索引
    a_idx = {a.id: a for a in analyzed}

    # 1. 切每段
    if logger:
        logger.info(f"[render] 切 {len(board.selected)} 个瞬时，色调={color_grade}")
    outs = []
    timeline = []
    total = 0.0
    for item in board.selected:
        a = a_idx.get(item.id)
        if not a:
            continue
        us, ue = item.use_start, item.use_end
        if us is None or ue is None:
            us, ue = a.start, a.end
        out = clips_dir / f"{item.order:02d}_{item.id}.mp4"
        if not (out.exists() and out.stat().st_size > 5000):
            ok = cut_clip(a.src, us, ue, out, config.ffmpeg_path, grade_filter, crf, logger)
            if not ok:
                continue
        dur = ue - us
        timeline.append({
            "order": item.order, "id": item.id,
            "t_start": total, "t_end": total + dur,
            "duration": dur, "subtitle": item.subtitle,
        })
        total += dur
        outs.append(out)

    if not outs:
        raise RuntimeError("没有可用切片")

    # 2. concat
    if logger:
        logger.info(f"[render] concat {len(outs)} 个 → {merged.name}")
    concat(outs, concat_file, merged, config.ffmpeg_path, logger)

    # 3. 字幕
    write_ass(timeline, ass_path, ass_fontsize, ass_outline, ass_marginv)

    # 4. BGM + 烧入字幕
    if config.bgm_path and config.bgm_path.exists():
        if logger:
            logger.info(f"[render] 加 BGM (atempo={bgm_atempo}) + 字幕")
        add_bgm_and_subtitles(
            merged, config.bgm_path, output,
            ass_path if ass_path.exists() else None,
            config.ffmpeg_path,
            atempo=bgm_atempo, bgm_volume=bgm_volume,
            fade_in=fade_in, fade_out=fade_out,
            total_dur=total, crf=crf, logger=logger,
        )
    else:
        # 无 BGM，只烧字幕
        cmd = [str(config.ffmpeg_path), "-y", "-i", str(merged)]
        if ass_path.exists():
            cmd += ["-vf", f"subtitles='{ass_path.name}'"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                str(output)]
        subprocess.run(cmd, capture_output=True, timeout=600, cwd=str(job_dir / "work"))

    if logger:
        logger.info(f"[render] 成片: {output}")
    return output
