"""验证 GOP 编码参数：复用老任务的 analyzed + storyboard，重跑 render。

只验证 render.py 编码参数（GOP/B-frame/faststart/maxrate）对马赛克/卡顿的改善，
跳过 vision/LLM 阶段。

用法：
    python scripts/verify_gop_render.py <source_job_id> <new_job_id>

会把 source job 的 work/analyzed.json + work/storyboard.json 复制到新 job，
然后调 render.render(force_recut=True) 重新切片 + 合并。
"""
from __future__ import annotations
import json
import logging
import shutil
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from video_worker.render import render
from video_worker.validators import Storyboard, AnalyzedScene, JobConfig, Style, Platform, Provider


def main() -> int:
    if len(sys.argv) < 3:
        print("用法: python scripts/verify_gop_render.py <source_job_id> <new_job_id> [xfade_dur] [no_stab]")
        print("  xfade_dur 默认 0.0（硬切），建议试 0.3")
        print("  no_stab=1 时强制关闭 vidstab（诊断用）")
        return 2

    src_id, new_id = sys.argv[1], sys.argv[2]
    xfade_dur = float(sys.argv[3]) if len(sys.argv) >= 4 else 0.0
    no_stab = (len(sys.argv) >= 5 and sys.argv[4] == "1")
    work_root = _PROJECT_ROOT / "jobs"
    src_dir = work_root / src_id
    new_dir = work_root / new_id

    if not src_dir.exists():
        print(f"源任务不存在: {src_dir}")
        return 1

    # 准备新 job 目录
    for sub in ["work", "output"]:
        (new_dir / sub).mkdir(parents=True, exist_ok=True)

    # 复用 analyzed + storyboard
    for name in ["analyzed.json", "storyboard.json", "scenes.json"]:
        src_f = src_dir / "work" / name
        if src_f.exists():
            shutil.copy2(src_f, new_dir / "work" / name)

    # 加载
    analyzed_data = json.loads((new_dir / "work" / "analyzed.json").read_text(encoding="utf-8"))
    storyboard_data = json.loads((new_dir / "work" / "storyboard.json").read_text(encoding="utf-8"))

    # 转 Pydantic
    analyzed = [AnalyzedScene(**a) for a in analyzed_data]
    if no_stab:
        for a in analyzed:
            a.needs_stabilization = False
            a.shaky = False
    board = Storyboard(**storyboard_data)

    # 读取源任务 config
    src_cfg = json.loads((src_dir / "logs" / "job_config.json").read_text(encoding="utf-8"))
    config = JobConfig(
        job_id=new_id,
        input_path=src_cfg["input_path"],
        platform=Platform(src_cfg["platform"]),
        style=Style(src_cfg["style"]),
        target_duration=src_cfg["target_duration"],
        provider=Provider(src_cfg["provider"]),
        work_root=str(work_root),
        ffmpeg_path=src_cfg.get("ffmpeg_path", "tools\\ffmpeg.exe"),
    )

    # logger
    (new_dir / "logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(new_dir / "logs" / "job.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger("verify_gop")

    logger.info(f"=== verify_gop_render: {src_id} → {new_id} (xfade={xfade_dur}s, no_stab={no_stab}) ===")
    logger.info(f"selected 段数: {len(board.selected)}")

    # 调 render，force_recut=True 强制重切（应用新 GOP 参数）
    output = render(
        board, analyzed, config, new_dir,
        color_grade="cool_strong",
        xfade_dur=xfade_dur,
        force_recut=True,
        logger=logger,
    )

    logger.info(f"=== 完成: {output} ===")
    size_mb = output.stat().st_size / 1024 / 1024
    logger.info(f"文件大小: {size_mb:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
