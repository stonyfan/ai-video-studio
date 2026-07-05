"""
檀道2 第二阶段：抖动稳定
- 输入：clips_dao2/*.mp4（37 段 720p 竖屏，已去音）
- 处理：ffmpeg vidstab 两步法（detect + transform），每段独立稳定
- 输出：clips_dao2_stab/*.mp4 + merged_dao2_stab.mp4 + final_dao2_stab.mp4
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
FFMPEG = str(ROOT / "ffmpeg.exe")
SRC_CLIPS = ROOT / "clips_dao2"
STAB_CLIPS = ROOT / "clips_dao2_stab"
TRF_DIR = ROOT / "trf"
CONCAT_FILE = ROOT / "concat_dao2_stab.txt"
MERGED = ROOT / "merged_dao2_stab.mp4"
BGM = ROOT / "bgm_dao2.mp3"
FINAL = ROOT / "final_dao2_stab.mp4"

# vidstab 参数
SHAKINESS = 5
ACCURACY = 10
SMOOTHING = 30
ZOOM = 5


def log(msg):
    print(f"[stab] {msg}", flush=True)


def get_duration(path):
    r = subprocess.run([FFMPEG, "-i", str(path), "-f", "null", "-"],
                       capture_output=True, timeout=600)
    err = r.stderr.decode("utf-8", errors="replace")
    m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
    if m:
        h, mn, s = m.groups()
        return int(h) * 3600 + int(mn) * 60 + float(s)
    return None


def stabilize_one(src, trf_path, out_path):
    # 关键：ffmpeg 滤镜字符串里 Windows 反斜杠会被当转义符，绝对路径的冒号 `C:`
    # 也会被当参数分隔符。所以传给滤镜和 -i 的路径都用相对路径 + 正斜杠。
    # subprocess 的 cwd 是 ROOT（脚本启动时 chdir）。
    src_arg = src.relative_to(ROOT).as_posix()      # clips_dao2/02.mp4
    trf_arg = trf_path.relative_to(ROOT).as_posix() # trf/02.trf
    out_arg = out_path.relative_to(ROOT).as_posix() # clips_dao2_stab/02.mp4
    # 步骤 1：检测，生成 trf
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

    # 步骤 2：变换
    transform_cmd = [
        FFMPEG, "-y", "-i", src_arg,
        "-vf",
        f"vidstabtransform=input={trf_arg}:smoothing={SMOOTHING}:zoom={ZOOM}:optzoom=1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-an",
        "-r", "25",
        out_arg,
    ]
    r2 = subprocess.run(transform_cmd, capture_output=True, timeout=900, cwd=str(ROOT))
    if r2.returncode != 0:
        err = r2.stderr.decode("utf-8", errors="replace")[-1500:]
        log(f"  transform 失败: {src.name}\n{err}")
        return False
    return True


def step_stabilize():
    STAB_CLIPS.mkdir(exist_ok=True)
    TRF_DIR.mkdir(exist_ok=True)
    srcs = sorted(SRC_CLIPS.glob("*.mp4"))
    log(f"待稳定 {len(srcs)} 段")
    success = 0
    failed = []
    for src in srcs:
        name = src.stem  # "01", "02", ...
        trf = TRF_DIR / f"{name}.trf"
        out = STAB_CLIPS / f"{name}.mp4"
        if out.exists() and out.stat().st_size > 10000 and trf.exists():
            log(f"  [{name}] 已存在，跳过")
            success += 1
            continue
        log(f"  [{name}] 稳定中...")
        ok = stabilize_one(src, trf, out)
        if ok:
            d = get_duration(out)
            log(f"      完成，时长 {d:.2f}s")
            success += 1
        else:
            # 失败时直接复制原文件作 fallback
            log(f"      ⚠ 失败，回退用原版")
            import shutil
            shutil.copy2(src, out)
            failed.append(name)
    log(f"完成：{success}/{len(srcs)} 成功" + (f"，回退 {len(failed)} 段: {failed}" if failed else ""))
    return success


def step_concat():
    clips = sorted(STAB_CLIPS.glob("*.mp4"))
    CONCAT_FILE.write_text(
        "\n".join(f"file 'clips_dao2_stab/{c.name}'" for c in clips) + "\n",
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
        log(f"BGM 不存在: {BGM}，输出无音视频")
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
    step_stabilize()
    dur = step_concat()
    step_add_bgm(dur)
    log("全部完成")
