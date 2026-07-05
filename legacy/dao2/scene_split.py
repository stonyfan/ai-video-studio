"""
檀道2 第五阶段 step 1+2: PySceneDetect 切场景 + 抽代表帧
输入：clips_dao2_v4/*.mp4（37 段稳定版）
输出：
  - dao2_scenes_raw.json  场景列表（id/src/start/end/dur）
  - _scene_probe/*.jpg    每场景代表帧
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

from scenedetect import open_video, SceneManager, ContentDetector

ROOT = Path(r"C:\Users\86150\video-project")
FFMPEG = str(ROOT / "ffmpeg.exe")
SRC_DIR = ROOT / "clips_dao2_v4"
PROBE_DIR = ROOT / "_scene_probe"
RAW_JSON = ROOT / "dao2_scenes_raw.json"

THRESHOLD = 27  # ContentDetector 默认值
MIN_LEN = 0.4   # 短于 0.4s 的场景丢弃（拼接时太短易跳）


def log(msg):
    print(f"[split] {msg}", flush=True)


def split_scenes():
    PROBE_DIR.mkdir(exist_ok=True)
    srcs = sorted(SRC_DIR.glob("*.mp4"))
    log(f"待处理 {len(srcs)} 段")

    scenes_dict = {}
    total_scenes = 0

    for src in srcs:
        seg_id = src.stem  # "01", "02"
        try:
            video = open_video(str(src))
            sm = SceneManager()
            sm.add_detector(ContentDetector(threshold=THRESHOLD))
            sm.detect_scenes(video)
            scene_list = sm.get_scene_list()
        except Exception as e:
            log(f"  [{seg_id}] 失败: {e}")
            continue

        if not scene_list:
            # 整段当成 1 个场景
            scene_list = []

        # scene_list 是 [(start_time, end_time), ...]，Timecode 对象
        kept = []
        for i, (start_tc, end_tc) in enumerate(scene_list):
            start = start_tc.get_seconds()
            end = end_tc.get_seconds()
            dur = end - start
            if dur < MIN_LEN:
                continue
            kept.append((i, start, end, dur))

        # 如果整段没切（只 1 个场景或 0 个），用整段
        if not kept:
            # 用 ffprobe 取时长
            r = subprocess.run([FFMPEG, "-i", str(src), "-f", "null", "-"],
                               capture_output=True, timeout=120)
            err = r.stderr.decode("utf-8", errors="replace")
            import re
            m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
            if m:
                h, mn, s = m.groups()
                total = int(h)*3600 + int(mn)*60 + float(s)
                kept = [(0, 0.0, total, total)]

        for sc_idx, start, end, dur in kept:
            scene_id = f"{seg_id}_{sc_idx}"
            scenes_dict[scene_id] = {
                "id": scene_id,
                "src": str(src.relative_to(ROOT)).replace("\\", "/"),
                "seg": seg_id,
                "sc_idx": sc_idx,
                "start": round(start, 3),
                "end": round(end, 3),
                "dur": round(dur, 3),
            }
            total_scenes += 1

        log(f"  [{seg_id}] 切出 {len(kept)} 个场景")

    RAW_JSON.write_text(json.dumps(scenes_dict, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    log(f"完成：共 {total_scenes} 个场景 -> {RAW_JSON.name}")
    return scenes_dict


def extract_probes(scenes_dict):
    log(f"抽代表帧到 {PROBE_DIR}")
    cnt = 0
    for scene_id, sc in scenes_dict.items():
        mid = (sc["start"] + sc["end"]) / 2
        src = ROOT / sc["src"]
        out = PROBE_DIR / f"{scene_id}.jpg"
        if out.exists() and out.stat().st_size > 3000:
            cnt += 1
            continue
        cmd = [FFMPEG, "-y", "-ss", str(mid), "-i", str(src),
               "-vframes", "1", "-update", "1",
               "-vf", "scale=360:-1", "-q:v", "3", str(out)]
        r = subprocess.run(cmd, capture_output=True, timeout=30, cwd=str(ROOT))
        if out.exists() and out.stat().st_size > 3000:
            cnt += 1
    log(f"代表帧：{cnt}/{len(scenes_dict)}")


if __name__ == "__main__":
    scenes = split_scenes()
    extract_probes(scenes)
    log("完成")
