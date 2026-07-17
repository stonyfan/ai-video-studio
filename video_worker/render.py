"""
渲染：FFmpeg 切片 + 节拍对齐 + 色调 + 字幕 + BGM
"""
from __future__ import annotations
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .validators import JobConfig, Storyboard, AnalyzedScene


# 色调预设（参考 legacy/yulan/multi_build.py PLATFORM_CONFIG）
# unsharp 强度统一降到 0.3 避免放大 H.264 块效应（两次编码级联时尤其明显）
#
# vidstab 默认关闭：smoothing=30 在段头/段尾产生帧错位（用户感知为乱码+回撤）。
# 三脚架/稳定器素材不需要；真手抖素材需要时改 True 并调小 smoothing。
ENABLE_VIDSTAB = False

COLOR_GRADES = {
    "cool_strong": (
        "eq=saturation=0.80,"
        "colorbalance=bs=0.25:bm=0.15:bh=-0.08,"
        "curves=preset=increase_contrast,"
        "unsharp=3:3:0.3:3:3:0,"
        "eq=brightness=0.04:saturation=1.12"
    ),
    "warm": (
        "eq=saturation=0.92,"
        "colorbalance=rs=0.12:rm=0.10:rh=0.05:gs=0.03:gm=0.02,"
        "curves=preset=lighter,"
        "unsharp=3:3:0.3:3:3:0,"
        "eq=brightness=0.05:saturation=0.95:gamma=0.95"
    ),
    "natural": (
        "eq=saturation=0.95,"
        "colorbalance=bs=0.08:bm=0.04,"
        "curves=preset=increase_contrast,"
        "unsharp=3:3:0.3:3:3:0,"
        "eq=brightness=0.02:saturation=1.0"
    ),
}


def _abs(p: Path) -> str:
    """转绝对路径并正斜杠（避免 Windows cwd 子路径问题）"""
    return str(p.resolve()).replace("\\", "/")


def cut_clip(src: Path, us: float, ue: float, out: Path,
             ffmpeg_path: Path, grade_filter: str,
             crf: int = 20, stabilize: bool = False,
             trf_dir: Optional[Path] = None,
             logger: Optional[logging.Logger] = None) -> bool:
    """切单段，应用色调滤镜；可选 vidstab 稳定（两步：detect + transform）。

    不加 fade in/out：相邻切片往往来自同一源视频的相邻时间段，硬切最自然；
    fade to black 反而引入黑屏闪烁。真要做无缝转场应该用 xfade（未来工作）。
    """
    cwd = None
    if stabilize and trf_dir is not None:
        trf_dir.mkdir(parents=True, exist_ok=True)
        # ffmpeg filter 不支持绝对路径里的冒号（Windows C:），
        # 用纯文件名 + 设置 cwd 到 trf_dir 绕过
        trf_name = f"{out.stem}.trf"
        cwd = str(trf_dir)
        # 1. vidstabdetect 生成 trf 文件
        detect_cmd = [
            _abs(ffmpeg_path), "-y",
            "-ss", f"{us:.3f}", "-to", f"{ue:.3f}",
            "-i", _abs(src),
            "-vf", f"vidstabdetect=result={trf_name}",
            "-f", "null", "-",
        ]
        subprocess.run(detect_cmd, capture_output=True, timeout=120, cwd=cwd)
        # 2. vidstabtransform + 色调（zoom=1.1 补偿边缘裁剪）
        vf = f"vidstabtransform=smoothing=30:input={trf_name}:zoom=1.1,{grade_filter}"
    else:
        vf = grade_filter

    cmd = [
        _abs(ffmpeg_path), "-y",
        "-ss", f"{us:.3f}", "-to", f"{ue:.3f}",
        "-i", _abs(src),
        "-vf", vf,
        # fast：单段切本来就短，medium 提速不显著且拖慢整体
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-an", "-r", "25",
        "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "2",
        _abs(out),
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=180, cwd=cwd)
    ok = r.returncode == 0 and out.exists() and out.stat().st_size > 5000
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"切片失败 {src.name}: {err}")
    return ok


def concat(clips: list[Path], concat_file: Path, output: Path,
           ffmpeg_path: Path, logger: Optional[logging.Logger] = None) -> bool:
    """concat demuxer：file 路径相对于 concat_file 所在目录。

    注意：调用方必须按目标顺序传入 clips，本函数不再 sort（避免 storyboard order 被字典序打乱）。
    """
    base = concat_file.parent
    lines = []
    for c in clips:
        # 相对 concat_file 的路径（用正斜杠）
        try:
            rel = c.relative_to(base).as_posix()
        except ValueError:
            rel = str(c.resolve()).replace("\\", "/")
        lines.append(f"file '{rel}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cmd = [_abs(ffmpeg_path), "-y", "-f", "concat", "-safe", "0",
           "-i", _abs(concat_file), "-c", "copy", _abs(output)]
    r = subprocess.run(cmd, capture_output=True, timeout=300)
    ok = r.returncode == 0
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-600:]
        logger.error(f"concat 失败: {err}")
    return ok


def concat_with_xfade(segments: list[Path], segment_durs: list[float],
                      output: Path, ffmpeg_path: Path,
                      xfade_dur: float = 0.3,
                      logger: Optional[logging.Logger] = None) -> bool:
    """用 xfade 转场合并多段（每段已是独立 mp4，通常来自 concat 后的同 src 切片组）。

    xfade 链式：
      [0:v][1:v]xfade=transition=fade:duration=X:offset=O1[v01];
      [v01][2:v]xfade=...[vout]
    offset for xfade i = sum(d[0..i-1]) - i*X
    总时长 = sum(d) - (N-1)*X

    设计动机：硬切跨源片段会有"幻灯片"感，xfade 在 src 切换边界平滑过渡。
    同 src 内部仍硬切（保持时序连续性）。
    """
    if not segments:
        return False
    if len(segments) == 1:
        shutil.copy(segments[0], output)
        return True

    cmd = [_abs(ffmpeg_path), "-y"]
    for seg in segments:
        cmd += ["-i", _abs(seg)]

    n = len(segments)
    parts = []
    prev_label = "0:v"
    cumulative = segment_durs[0]
    for i in range(1, n):
        offset = max(0.0, cumulative - i * xfade_dur)
        out_label = "vout" if i == n - 1 else f"v{i:02d}"
        parts.append(
            f"[{prev_label}][{i}:v]xfade=transition=fade:"
            f"duration={xfade_dur}:offset={offset:.3f}[{out_label}]"
        )
        prev_label = out_label
        cumulative += segment_durs[i]

    cmd += ["-filter_complex", ";".join(parts),
            "-map", "[vout]", "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "16",
            "-pix_fmt", "yuv420p",
            "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "2",
            _abs(output)]
    r = subprocess.run(cmd, capture_output=True, timeout=600)
    ok = r.returncode == 0 and output.exists() and output.stat().st_size > 10000
    if not ok and logger:
        err = r.stderr.decode("utf-8", errors="replace")[-1000:]
        logger.error(f"concat_with_xfade 失败: {err}")
    return ok


def _group_into_segments(outs: list[Path], clip_srcs: list[Path],
                         clip_durs: list[float],
                         segs_dir: Path, ffmpeg_path: Path,
                         logger: Optional[logging.Logger] = None
                         ) -> tuple[list[tuple[Path, float]], list[int]]:
    """按 src 分组连续切片，同 src 用 concat 合成 segment；返回 (segments, clip_seg_idx)。

    segments: [(path, dur)] 每段路径与时长
    clip_seg_idx: 每个 outs 对应的 segment 索引（用于 timeline 偏移校正）
    """
    segs_dir.mkdir(parents=True, exist_ok=True)

    # 第一遍：找组边界（src 变化的索引）
    boundaries = [0]
    for j in range(1, len(outs)):
        if clip_srcs[j] != clip_srcs[j - 1]:
            boundaries.append(j)

    # 第二遍：分配 clip_seg_idx + 构建 segments
    clip_seg_idx: list[int] = [0] * len(outs)
    segments: list[tuple[Path, float]] = []
    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else len(outs)
        for j in range(start, end):
            clip_seg_idx[j] = i
        seg_clips = outs[start:end]
        seg_dur = sum(clip_durs[start:end])
        if len(seg_clips) == 1:
            seg_path = seg_clips[0]
        else:
            seg_path = segs_dir / f"seg_{i:02d}.mp4"
            seg_cf = segs_dir / f"seg_{i:02d}.txt"
            if not concat(seg_clips, seg_cf, seg_path, ffmpeg_path, logger):
                raise RuntimeError(f"段内 concat 失败: {seg_path}")
        segments.append((seg_path, seg_dur))
    return segments, clip_seg_idx


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


def _escape_filter_path(p: Path) -> str:
    """ffmpeg filter 里转义 : 和 ' （Windows 路径必备）"""
    s = _abs(p)
    return s.replace(":", "\\:").replace("'", "\\'")


def verify_final(final_path: Path, ffmpeg_path: Path,
                 expected_dur: float = 0.0,
                 logger: Optional[logging.Logger] = None) -> float:
    """ffprobe 风格读 final.mp4 时长 + 文件大小校验。

    返回实际时长（秒）。失败抛 RuntimeError —— 防止 render() 误报成功。
    """
    if not final_path.exists() or final_path.stat().st_size < 10_000:
        raise RuntimeError(
            f"final.mp4 不存在或过小 (<10KB): {final_path}"
        )
    cmd = [_abs(ffmpeg_path), "-i", _abs(final_path), "-f", "null", "-"]
    r = subprocess.run(cmd, capture_output=True, timeout=120)
    err = r.stderr.decode("utf-8", errors="replace")
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
    if not m:
        raise RuntimeError(
            f"final.mp4 无法读时长（可能损坏）: stderr={err[-400:]}"
        )
    h, mn, s = m.groups()
    dur = int(h) * 3600 + int(mn) * 60 + float(s)
    if dur <= 0.1:
        raise RuntimeError(f"final.mp4 时长异常: {dur:.3f}s")
    if expected_dur > 0 and dur < expected_dur * 0.5:
        if logger:
            logger.warning(
                f"[verify] final.mp4 时长 {dur:.1f}s 远低于预期 {expected_dur:.1f}s "
                f"（可能多段切失败被跳过）"
            )
    elif logger:
        logger.info(f"[verify] final.mp4 时长 {dur:.2f}s ({final_path.stat().st_size // 1024} KB)")
    return dur


def add_bgm_and_subtitles(merged: Path, bgm: Path, output: Path,
                          ass_path: Optional[Path], ffmpeg_path: Path,
                          atempo: float = 1.0, bgm_volume: float = 0.85,
                          fade_in: float = 1.0, fade_out: float = 1.5,
                          total_dur: float = 0.0,
                          crf: int = 20, logger: Optional[logging.Logger] = None) -> bool:
    cmd = [_abs(ffmpeg_path), "-y", "-i", _abs(merged),
           "-stream_loop", "-1", "-i", _abs(bgm)]
    if ass_path:
        cmd += ["-vf", f"subtitles='{_escape_filter_path(ass_path)}'"]
    fade_out_start = max(0, total_dur - fade_out)
    audio_chain = f"atempo={atempo},volume={bgm_volume},afade=t=in:st=0:d={fade_in},afade=t=out:st={fade_out_start}:d={fade_out}"
    cmd += [
        "-filter_complex", f"[1:a]{audio_chain}[a]",
        "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "2",
        "-movflags", "+faststart", "-maxrate", "10M", "-bufsize", "20M",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", _abs(output),
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
           xfade_dur: float = 0.0,
           force_recut: bool = False,
           output_filename: str = "final.mp4",
           logger: Optional[logging.Logger] = None) -> Path:
    """主渲染：切每段 → concat（或 xfade 跨源转场）→ 字幕+BGM

    xfade_dur > 0 时：同 src 连续切片用 concat 硬接（保持时序连续），
    跨 src 边界用 xfade 平滑过渡。timeline 会按 xfade 偏移自动校正。

    force_recut: True 时忽略 final_clips/ 缓存强制重切。
        默认 False（resume 模式下省时间）。
        改 storyboard 重渲染（不同 use_start/use_end/cut_duration）时必须 True，
        否则会用旧 cut window 的 clip 导致新时长不生效。
    """
    clips_dir = job_dir / "work" / "final_clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    stab_dir = job_dir / "work" / "stab"
    concat_file = job_dir / "work" / "concat.txt"
    merged = job_dir / "work" / "merged.mp4"
    ass_path = job_dir / "work" / "subtitles.ass"
    output = job_dir / "output" / output_filename

    grade_filter = COLOR_GRADES.get(color_grade, COLOR_GRADES["natural"])

    # analyzed 索引
    a_idx = {a.id: a for a in analyzed}

    # 1. 切每段
    stab_count = 0
    if logger:
        logger.info(f"[render] 切 {len(board.selected)} 个瞬时，色调={color_grade}，xfade={xfade_dur}s")
    outs = []
    clip_srcs: list[Path] = []
    clip_durs: list[float] = []
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
        # 稳定条件：全局开关 + GLM 判定该稳 + 光流确认有抖
        stabilize = ENABLE_VIDSTAB and bool(a.needs_stabilization and a.shaky)
        if stabilize:
            stab_count += 1
            if logger:
                logger.info(f"[render] {item.id}: 应用 vidstab 稳定")
        cached = out.exists() and out.stat().st_size > 5000
        if force_recut and cached:
            out.unlink()
            cached = False
        if not cached:
            ok = cut_clip(a.src, us, ue, out, config.ffmpeg_path, grade_filter, crf,
                          stabilize=stabilize, trf_dir=stab_dir, logger=logger)
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
        clip_srcs.append(a.src)
        clip_durs.append(dur)

    if not outs:
        raise RuntimeError("没有可用切片")

    # 2. concat（或 xfade 跨源转场）
    if xfade_dur > 0 and len(outs) > 1:
        segs_dir = job_dir / "work" / "segments"
        try:
            segments, clip_seg_idx = _group_into_segments(
                outs, clip_srcs, clip_durs,
                segs_dir, config.ffmpeg_path, logger,
            )
        except RuntimeError as e:
            raise RuntimeError(f"段分组失败: {e}")

        n_seg = len(segments)
        if logger:
            if stab_count > 0:
                logger.info(f"[render] 共 {stab_count} 个切片应用了 vidstab 稳定")
            logger.info(f"[render] 分 {n_seg} 段（同 src 内 concat 硬接，跨 src 用 xfade={xfade_dur}s）")

        if n_seg == 1:
            shutil.copy(segments[0][0], merged)
        else:
            # timeline 校正：每个 clip 在 final 中的实际时间 = 原时间 - seg_idx * xfade_dur
            for t in timeline:
                seg_idx = clip_seg_idx[t["order"] - 1]
                adj = seg_idx * xfade_dur
                t["t_start"] = max(0.0, t["t_start"] - adj)
                t["t_end"] = max(0.0, t["t_end"] - adj)
            total -= (n_seg - 1) * xfade_dur

            if not concat_with_xfade(
                [s[0] for s in segments], [s[1] for s in segments],
                merged, config.ffmpeg_path,
                xfade_dur=xfade_dur, logger=logger,
            ):
                raise RuntimeError(f"xfade 合并失败: {merged}")
    else:
        if logger:
            if stab_count > 0:
                logger.info(f"[render] 共 {stab_count} 个切片应用了 vidstab 稳定")
            logger.info(f"[render] concat {len(outs)} 个 → {merged.name}")
        if not concat(outs, concat_file, merged, config.ffmpeg_path, logger):
            raise RuntimeError(f"concat 失败，merged 未生成: {merged}")
    if not merged.exists() or merged.stat().st_size < 10_000:
        raise RuntimeError(f"concat 后 merged.mp4 不存在或过小: {merged}")

    # 3. 字幕
    write_ass(timeline, ass_path, ass_fontsize, ass_outline, ass_marginv)

    # 4. BGM + 烧入字幕
    if config.bgm_path and config.bgm_path.exists():
        if logger:
            logger.info(f"[render] 加 BGM (atempo={bgm_atempo}) + 字幕")
        if not add_bgm_and_subtitles(
            merged, config.bgm_path, output,
            ass_path if ass_path.exists() else None,
            config.ffmpeg_path,
            atempo=bgm_atempo, bgm_volume=bgm_volume,
            fade_in=fade_in, fade_out=fade_out,
            total_dur=total, crf=crf, logger=logger,
        ):
            raise RuntimeError(f"add_bgm_and_subtitles 失败: {output}")
    else:
        # 无 BGM，只烧字幕
        cmd = [_abs(config.ffmpeg_path), "-y", "-i", _abs(merged)]
        if ass_path.exists():
            cmd += ["-vf", f"subtitles='{_escape_filter_path(ass_path)}'"]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
                "-g", "50", "-keyint_min", "50", "-sc_threshold", "0", "-bf", "2",
                "-movflags", "+faststart", "-maxrate", "10M", "-bufsize", "20M",
                _abs(output)]
        r = subprocess.run(cmd, capture_output=True, timeout=600)
        if r.returncode != 0:
            err = r.stderr.decode("utf-8", errors="replace")[-1000:]
            raise RuntimeError(f"渲染失败（无 BGM 分支）: {err}")
        if logger:
            logger.info(f"[render] 无 BGM 成片: {output}")

    # 5. ffprobe 校验 final.mp4（防止坏文件被标记 COMPLETED）
    verify_final(output, config.ffmpeg_path, expected_dur=total, logger=logger)

    if logger:
        logger.info(f"[render] 成片: {output}")
    return output
