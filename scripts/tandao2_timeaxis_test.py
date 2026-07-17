"""
Phase 15 时间轴方案验证（独立脚本，不接 job.py）：
1. 复用 jobs/tandao2_edl/work/analyzed.json（不重新调 VLM）
2. 读每个源视频的 creation_time（ffprobe）当时间轴
3. pHash + main_objects 内容去重
4. 按拍摄时间排序，构建 Storyboard
5. 复用 render.py 渲染

输出：jobs/tandao2_timeaxis/output/final.mp4
"""
from __future__ import annotations
import json
import logging
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("ZHIPU_API_KEY", "253e42f83cff402b8e2c2825dbee3310.qRIdGGx9MvzIG9IC")

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import imagehash
from PIL import Image

from video_worker import render as render_mod
from video_worker.validators import (
    AnalyzedScene, JobConfig, Storyboard, StoryboardItem, Style, Provider,
)
from video_worker.paths import resolve_ffmpeg


# === 配置 ===
SOURCE_JOB = Path("jobs/tandao2_edl")
NEW_JOB = Path("jobs/tandao2_timeaxis")
SOURCE_VIDEOS_DIR = Path(r"C:\Users\86150\Downloads\檀道2")
TARGET_DURATION = 30.0
PHASH_THRESHOLD = 8              # Hamming distance < 8 视为视觉重复
REQUIRE_SAME_MAIN_OBJECTS = True # L2：phash 像且 main_objects 一样才判重


def read_creation_time(ffprobe: Path, video_path: Path) -> str:
    """读 MP4 元数据里的 creation_time（拍摄时间）。返回 bytes 再解码，避开 GBK。"""
    try:
        result = subprocess.run(
            [str(ffprobe), "-hide_banner", "-i", str(video_path)],
            capture_output=True, timeout=10,
        )
        # stderr 是 bytes，按 utf-8 errors='replace' 解码，避免 GBK 崩
        err_text = (result.stderr or b"").decode("utf-8", errors="replace")
        m = re.search(r"creation_time\s*:\s*(\S+)", err_text)
        return m.group(1) if m else ""
    except Exception:
        return ""


def get_representative_frame(scene_id: str, frames_seq_dir: Path) -> Path | None:
    """拿场景的代表帧（中间那张）。"""
    pattern = f"{scene_id}_f*.jpg"
    frames = sorted(frames_seq_dir.glob(pattern))
    if not frames:
        return None
    return frames[len(frames) // 2]  # 中间帧


def compute_phash(image_path: Path) -> imagehash.ImageHash | None:
    try:
        return imagehash.phash(Image.open(image_path), hash_size=16)
    except Exception:
        return None


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger = logging.getLogger("timeaxis")

    # 1. 复用现有产物
    analyzed_data = json.loads((SOURCE_JOB / "work" / "analyzed.json").read_text(encoding="utf-8"))
    print(f"[1] 加载 analyzed.json: {len(analyzed_data)} 段")

    # 2. 读每个源视频的 creation_time
    ffprobe = resolve_ffmpeg(Path("tools/ffmpeg.exe"))
    source_files = sorted(SOURCE_VIDEOS_DIR.glob("*.MP4"))
    src_to_time = {}
    for src in source_files:
        ct = read_creation_time(ffprobe, src)
        src_to_time[src.stem] = ct
    print(f"[2] 读到 {len(src_to_time)} 个源视频的 creation_time")
    # 看前 3 个
    for name in list(src_to_time.keys())[:3]:
        print(f"    {name}.MP4 → {src_to_time[name]}")

    # 3. 每个源视频选最佳场景（同源多场景里挑综合分最高的）
    src_group = defaultdict(list)
    for a in analyzed_data:
        seg = a["id"].rsplit("_", 1)[0]  # "01-1_0" → "01-1"
        src_group[seg].append(a)

    best_per_src = {}
    for seg, scenes in src_group.items():
        def score(a):
            return a["highlight_score"] * 0.5 + a["visual_quality"] * 0.3 + a["motion_score"] * 0.2
        best = max(scenes, key=score)
        best_per_src[seg] = best
    print(f"[3] {len(src_group)} 个源视频，每选取最佳场景 → {len(best_per_src)} 段")

    # 4. pHash + main_objects 去重
    frames_seq_dir = SOURCE_JOB / "work" / "frames_seq"
    survivors = []  # [(seg, scene, phash)]
    dropped = []

    # 按 creation_time 排序，前面的是"原版"，后面的是"重复"
    sorted_segs = sorted(
        best_per_src.keys(),
        key=lambda s: src_to_time.get(s, "9999"),
    )

    for seg in sorted_segs:
        scene = best_per_src[seg]
        frame_path = get_representative_frame(scene["id"], frames_seq_dir)
        if not frame_path:
            print(f"    [skip] {scene['id']}: 找不到代表帧")
            continue
        phash = compute_phash(frame_path)
        if phash is None:
            continue

        # 和已保留的场景比
        is_dup = False
        for prev_seg, prev_scene, prev_phash in survivors:
            distance = phash - prev_phash
            same_objs = set(scene.get("main_objects", [])) == set(prev_scene.get("main_objects", []))
            same_action = scene.get("action_type") == prev_scene.get("action_type")
            if distance < PHASH_THRESHOLD:
                if not REQUIRE_SAME_MAIN_OBJECTS or same_objs:
                    is_dup = True
                    dropped.append((seg, prev_seg, distance, "phash+objs"))
                    break
            elif same_objs and same_action:
                # 不同构图但主体+动作相同
                is_dup = True
                dropped.append((seg, prev_seg, distance, "objs+action"))
                break

        if not is_dup:
            survivors.append((seg, scene, phash))

    print(f"[4] 去重后保留 {len(survivors)} 段（淘汰 {len(dropped)} 段）")
    for seg, prev_seg, dist, reason in dropped[:10]:
        print(f"    drop {seg} (≈ {prev_seg}, distance={dist}, reason={reason})")
    if len(dropped) > 10:
        print(f"    ... 还有 {len(dropped)-10} 条")

    # 5. 按拍摄时间排序（已经在 sorted_segs 顺序里，survivors 也保持这个顺序）
    print(f"[5] 按 creation_time 排序")
    for i, (seg, scene, _) in enumerate(survivors, 1):
        ct = src_to_time.get(seg, "?")[:19]
        objs = "/".join(scene.get("main_objects", []))[:30]
        print(f"    {i:>2}. {seg:<10} ct={ct} objs={objs}")

    # 6. 构建 Storyboard
    num_segments = len(survivors)
    cut_per_segment = round(TARGET_DURATION / num_segments, 2)
    print(f"\n[6] 构建 Storyboard: {num_segments} 段 × {cut_per_segment}s = {num_segments*cut_per_segment:.1f}s")

    items = []
    for i, (seg, scene, _) in enumerate(survivors, 1):
        # 用 analyzed 的 best_moment 区域作为 use_start
        a_start = scene["start"]
        a_end = scene["end"]
        a_dur = a_end - a_start
        # 居中取 cut_per_segment，不够就缩到区间内
        desired = min(cut_per_segment, a_dur)
        use_start = a_start + (a_dur - desired) / 2
        use_end = use_start + desired
        items.append(StoryboardItem(
            order=i,
            id=scene["id"],
            cut_duration=round(use_end - use_start, 3),
            subtitle=None,
            use_start=round(use_start, 3),
            use_end=round(use_end, 3),
            reason="time-axis",
        ))

    board = Storyboard(
        narrative="檀道宣传片（时间轴方案：按拍摄时间排序 + pHash 去重）",
        target_duration_sec=int(TARGET_DURATION),
        expected_duration_sec=sum(it.cut_duration for it in items),
        selected=items,
    )

    # 7. 复制必要文件到新 job_dir，调用 render
    if NEW_JOB.exists():
        shutil.rmtree(NEW_JOB)
    new_work = NEW_JOB / "work"
    new_work.mkdir(parents=True)

    # 复制 clips/ 和 analyzed.json（render 需要）
    shutil.copytree(SOURCE_JOB / "work" / "clips", new_work / "clips")
    shutil.copy(SOURCE_JOB / "work" / "analyzed.json", new_work / "analyzed.json")
    (NEW_JOB / "output").mkdir()

    # 重建 analyzed list（从 dict）
    analyzed_list = [AnalyzedScene(**a) for a in analyzed_data]

    cfg = JobConfig(
        job_id="tandao2_timeaxis",
        input_path=str(SOURCE_VIDEOS_DIR),
        platform="general",
        style=Style.NARRATIVE,
        target_duration=int(TARGET_DURATION),
        provider=Provider.GLM,
        work_root="jobs",
        ffmpeg_path=str(resolve_ffmpeg(Path("tools/ffmpeg.exe"))),
        config_path=Path("configs/default.yaml"),
        natural_language_request="time-axis test",
    )

    print(f"\n[7] 调 render.py 渲染...")
    final_video = render_mod.render(
        board, analyzed_list, cfg, NEW_JOB,
        color_grade="natural",
        bgm_atempo=1.0,
        ass_fontsize=30,
        ass_outline=2.5,
        ass_marginv=100,
        crf=20,
        bgm_volume=0.85,
        fade_in=1.0,
        fade_out=1.5,
        xfade_dur=0.0,
        logger=logger,
    )

    # 8. 保存 storyboard
    (new_work / "storyboard_timeaxis.json").write_text(
        json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print()
    print("="*60)
    print(f"输出视频: {final_video}")
    print(f"Storyboard: {new_work / 'storyboard_timeaxis.json'}")
    print(f"段数: {num_segments}, 总时长: {board.expected_duration_sec:.2f}s")
    print(f"源视频利用率: {num_segments}/{len(source_files)} = {num_segments*100//len(source_files)}%")


if __name__ == "__main__":
    main()
