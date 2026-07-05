"""
yulan step 2: PySceneDetect 切场景
- 输入：clips/*.mp4
- 输出：scenes.json + _scene_probe/*.jpg
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

from scenedetect import open_video, SceneManager, ContentDetector

ROOT = Path(__file__).parent
PARENT = ROOT.parent
FFMPEG = str(PARENT / "ffmpeg.exe")
CLIPS_DIR = ROOT / "clips"
PROBE_DIR = ROOT / "_scene_probe"
SCENES_JSON = ROOT / "scenes.json"

THRESHOLD = 27
MIN_LEN = 0.4


def log(msg):
    print(f"[split] {msg}", flush=True)


def split_scenes():
    PROBE_DIR.mkdir(exist_ok=True)
    srcs = sorted(CLIPS_DIR.glob("*.mp4"))
    log(f"待处理 {len(srcs)} 段")
    scenes_dict = {}
    total = 0

    for src in srcs:
        seg_id = src.stem
        try:
            video = open_video(str(src))
            sm = SceneManager()
            sm.add_detector(ContentDetector(threshold=THRESHOLD))
            sm.detect_scenes(video)
            scene_list = sm.get_scene_list()
        except Exception as e:
            log(f"  [{seg_id}] 失败: {e}")
            continue

        kept = []
        for i, (start_tc, end_tc) in enumerate(scene_list):
            start = start_tc.get_seconds()
            end = end_tc.get_seconds()
            dur = end - start
            if dur >= MIN_LEN:
                kept.append((i, start, end, dur))

        if not kept:
            r = subprocess.run([FFMPEG, "-i", str(src), "-f", "null", "-"],
                               capture_output=True, timeout=120)
            err = r.stderr.decode("utf-8", errors="replace")
            m = re.search(r"Duration:\s+(\d+):(\d+):(\d+\.\d+)", err)
            if m:
                h, mn, s = m.groups()
                total_dur = int(h)*3600 + int(mn)*60 + float(s)
                kept = [(0, 0.0, total_dur, total_dur)]

        for sc_idx, start, end, dur in kept:
            scene_id = f"{seg_id}_{sc_idx}"
            scenes_dict[scene_id] = {
                "id": scene_id,
                "src": f"clips/{seg_id}.mp4",
                "seg": seg_id,
                "sc_idx": sc_idx,
                "start": round(start, 3),
                "end": round(end, 3),
                "dur": round(dur, 3),
            }
            total += 1

        log(f"  [{seg_id}] 切出 {len(kept)} 个场景")

    SCENES_JSON.write_text(json.dumps(scenes_dict, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    log(f"完成：共 {total} 个场景")
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
        subprocess.run(cmd, capture_output=True, timeout=30, cwd=str(ROOT))
        if out.exists() and out.stat().st_size > 3000:
            cnt += 1
    log(f"代表帧：{cnt}/{len(scenes_dict)}")


if __name__ == "__main__":
    scenes = split_scenes()
    extract_probes(scenes)
    log("完成")
