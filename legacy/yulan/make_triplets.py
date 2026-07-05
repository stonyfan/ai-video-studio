"""
yulan step 3: 三联图 + AI 高光检测
- 输入：scenes.json + _scene_probe/
- 输出：scenes_v6.json（含 best_frame + cut_duration 0.5-1.5s）
"""
import json
import subprocess
import sys
import sys as _sys
from pathlib import Path
from PIL import Image

try:
    _sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).parent
PARENT = ROOT.parent
FFMPEG = str(PARENT / "ffmpeg.exe")
SCENES_JSON = ROOT / "scenes.json"
PROBE_DIR = ROOT / "_scene_probe"
EXTRA_DIR = ROOT / "_scene_extra"
TRIPLET_DIR = ROOT / "_scene_triplet"
FRAME_W = 360


def log(msg):
    print(f"[tri] {msg}", flush=True)


def grab_frame(src, ts, out):
    src_arg = str(src).replace("\\", "/")
    out_arg = str(out).replace("\\", "/")
    cmd = [FFMPEG, "-y", "-ss", str(ts), "-i", src_arg,
           "-vframes", "1", "-update", "1",
           "-vf", f"scale={FRAME_W}:-1", "-q:v", "3", out_arg]
    subprocess.run(cmd, capture_output=True, timeout=30, cwd=str(ROOT))
    return out.exists() and out.stat().st_size > 3000


def make_triplet(scene):
    sid = scene["id"]
    src = ROOT / scene["src"]
    start, end = scene["start"], scene["end"]
    dur = end - start
    t25 = start + dur * 0.25
    t50 = start + dur * 0.50
    t75 = start + dur * 0.75

    f50 = PROBE_DIR / f"{sid}.jpg"
    if not (f50.exists() and f50.stat().st_size > 3000):
        grab_frame(src, t50, f50)
    f25 = EXTRA_DIR / f"{sid}_25.jpg"
    f75 = EXTRA_DIR / f"{sid}_75.jpg"
    if not (f25.exists() and f25.stat().st_size > 3000):
        grab_frame(src, t25, f25)
    if not (f75.exists() and f75.stat().st_size > 3000):
        grab_frame(src, t75, f75)

    out = TRIPLET_DIR / f"{sid}.jpg"
    if out.exists() and out.stat().st_size > 10000:
        return out
    imgs = []
    for f in [f25, f50, f75]:
        if not f.exists():
            return None
        im = Image.open(f).resize((FRAME_W, 640))
        imgs.append(im)
    canvas = Image.new("RGB", (FRAME_W * 3 + 20, 640), (20, 20, 20))
    canvas.paste(imgs[0], (0, 0))
    canvas.paste(imgs[1], (FRAME_W + 10, 0))
    canvas.paste(imgs[2], (FRAME_W * 2 + 20, 0))
    canvas.save(out, quality=85)
    return out


def main():
    EXTRA_DIR.mkdir(exist_ok=True)
    TRIPLET_DIR.mkdir(exist_ok=True)
    d = json.loads(SCENES_JSON.read_text(encoding="utf-8"))
    scenes = list(d.values())
    log(f"待处理 {len(scenes)} 场景")
    cnt = 0
    for sc in scenes:
        out = make_triplet(sc)
        if out:
            cnt += 1
    log(f"完成 {cnt}/{len(scenes)}")


if __name__ == "__main__":
    main()
