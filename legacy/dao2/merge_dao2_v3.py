"""
檀道2 第三阶段：智能裁剪 + 稳定 + BGM
- 输入：原始 4K 横屏源 + dao2_subject_positions.json
- 处理：根据 AI 分析的主体横向位置，对每段独立 crop（让主体居中）
- 输出：final_dao2_v3.mp4
"""
import subprocess
import re
import sys
import json
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

# 目录布局
CLIPS_V3 = ROOT / "clips_dao2_v3"           # 智能 crop 后（未稳定）
TRF_V3 = ROOT / "trf_v3"                     # 稳定变换数据
CLIPS_V3_STAB = ROOT / "clips_dao2_v3_stab"  # 智能 crop + 稳定后
CONCAT_FILE = ROOT / "concat_dao2_v3.txt"
MERGED = ROOT / "merged_dao2_v3.mp4"
BGM = ROOT / "bgm_dao2.mp3"
FINAL = ROOT / "final_dao2_v3.mp4"
POSITIONS_FILE = ROOT / "dao2_subject_positions.json"
ORDER_FILE = ROOT / "dao2_order.txt"

# vidstab 参数（同第二阶段）
SHAKINESS = 5
ACCURACY = 10
SMOOTHING = 30
ZOOM = 5

# 源视频规格
SRC_W = 3840
SRC_H = 2160
CROP_W_9X16 = int(SRC_H * 9 / 16)  # 1215


def log(msg):
    print(f"[v3] {msg}", flush=True)


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
    """返回 [(序号, 文件名), ...]，按 dao2_order.txt 的顺序"""
    order = []
    for line in ORDER_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            order.append((parts[0], parts[1]))
    return order


def compute_crop_x(subject_x_ratio):
    """根据主体横向位置算 crop_x，让主体居中（带边界保护）"""
    center_px = subject_x_ratio * SRC_W
    crop_x = int(center_px - CROP_W_9X16 / 2)
    # 边界保护
    crop_x = max(0, min(SRC_W - CROP_W_9X16, crop_x))
    return crop_x


def reencode_smart(src_path, out_path, subject_x_ratio):
    """根据主体位置 crop + scale 到 720p 竖屏"""
    crop_x = compute_crop_x(subject_x_ratio)
    src_arg = str(src_path).replace("\\", "/")
    out_arg = str(out_path).replace("\\", "/")
    vf = (f"crop={CROP_W_9X16}:{SRC_H}:{crop_x}:0,"
          f"scale=720:1280,setsar=1")

    cmd = [
        FFMPEG, "-y", "-i", src_arg,
        "-vf", vf,
        "-r", "25",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        out_arg,
    ]
    r = subprocess.run(cmd, capture_output=True, timeout=900)
    if r.returncode != 0:
        err = r.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"  重编码失败: {src_path.name}\n{err}")
        return False
    return True


def stabilize_one(src, trf_path, out_path):
    """复用第二阶段的稳定逻辑"""
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
        err = r1.stderr.decode("utf-8", errors="replace")[-800:]
        log(f"  detect 失败: {src.name}\n{err}")
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
    if r2.returncode != 0:
        err = r2.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"  transform 失败: {src.name}\n{err}")
        return False
    return True


def step_reencode():
    CLIPS_V3.mkdir(exist_ok=True)
    order = load_order()
    positions = json.loads(POSITIONS_FILE.read_text(encoding="utf-8"))
    log(f"开始智能裁剪重编码 {len(order)} 段")
    total_dur = 0.0
    for idx, name in order:
        src = SRC / name
        out = CLIPS_V3 / f"{idx}.mp4"
        if not src.exists():
            log(f"  [{idx}] 缺源文件: {name}")
            continue

        pos = positions.get(idx, {"subject_x": 0.5, "desc": "fallback center"})
        sx = pos["subject_x"]

        if out.exists() and out.stat().st_size > 10000:
            log(f"  [{idx}] 已存在，跳过 ({name}, x={sx})")
        else:
            crop_x = compute_crop_x(sx)
            log(f"  [{idx}] {name} x={sx} -> crop_x={crop_x}")
            ok = reencode_smart(src, out, sx)
            if not ok:
                continue
        d = get_duration(out)
        total_dur += d or 0
    log(f"重编码完成，总时长 {total_dur:.2f}s ({total_dur/60:.1f} 分钟)")
    return total_dur


def step_stabilize():
    TRF_V3.mkdir(exist_ok=True)
    CLIPS_V3_STAB.mkdir(exist_ok=True)
    clips = sorted(CLIPS_V3.glob("*.mp4"))
    log(f"开始稳定 {len(clips)} 段")
    success = 0
    for clip in clips:
        name = clip.stem  # "01"
        trf = TRF_V3 / f"{name}.trf"
        out = CLIPS_V3_STAB / f"{name}.mp4"
        if out.exists() and out.stat().st_size > 10000 and trf.exists():
            log(f"  [{name}] 已存在，跳过")
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
    clips = sorted(CLIPS_V3_STAB.glob("*.mp4"))
    CONCAT_FILE.write_text(
        "\n".join(f"file 'clips_dao2_v3_stab/{c.name}'" for c in clips) + "\n",
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
        err = r.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"concat 失败:\n{err}")
        sys.exit(1)
    dur = get_duration(MERGED)
    log(f"拼接完成: {MERGED.name} ({MERGED.stat().st_size/1024/1024:.1f} MB, {dur:.2f}s)")
    return dur


def step_add_bgm(video_dur):
    if not BGM.exists():
        log(f"BGM 不存在，输出无音视频")
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
        err = r.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"加 BGM 失败:\n{err}")
        sys.exit(1)
    log(f"成片: {FINAL.name} ({FINAL.stat().st_size/1024/1024:.1f} MB)")


if __name__ == "__main__":
    step_reencode()
    step_stabilize()
    dur = step_concat()
    step_add_bgm(dur)
    log("全部完成")
