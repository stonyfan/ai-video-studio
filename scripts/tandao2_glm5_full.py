"""
tandao2 glm-5.2 完整重跑：复用已有 analyzed.json（resume=True），切换 EDL 主模型为 glm-5.2。
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ZHIPU_API_KEY", "253e42f83cff402b8e2c2825dbee3310.qRIdGGx9MvzIG9IC")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from video_worker import job as job_mod
from video_worker.validators import JobConfig
from video_worker.paths import resolve_ffmpeg, bundled_config


def main():
    job_id = "tandao2_edl"
    job_dir = Path("jobs") / job_id

    # 备份 glm-4-plus 版本
    bak_dir = job_dir / "bak_glm4plus"
    bak_dir.mkdir(exist_ok=True)
    for src_name in ["edl.json", "storyboard.json", "output/final.mp4"]:
        src = job_dir / src_name
        if src.exists():
            dst = bak_dir / Path(src_name).name
            dst.write_bytes(src.read_bytes())
            print(f"备份: {src} → {dst}")

    cfg = JobConfig(
        job_id=job_id,
        input_path=r"C:\Users\86150\Downloads\檀道2",
        platform="general",
        style="narrative",
        target_duration=30,
        provider="glm",
        work_root="jobs",
        ffmpeg_path=str(resolve_ffmpeg(Path("tools/ffmpeg.exe"))),
        config_path=bundled_config(Path("configs/default.yaml")),
        natural_language_request="做成有故事感的檀道宣传片，展现从原料到成品的工匠精神",
    )

    # 构造 override config：开 EDL + 用 glm-5.2 主模型
    import yaml
    yaml_text = Path("configs/default.yaml").read_text(encoding="utf-8")
    yaml_text = yaml_text.replace(
        "edl:\n  enabled: false",
        "edl:\n  enabled: true",
    )
    yaml_text = yaml_text.replace(
        "primary_model: null",
        "primary_model: glm-5.2",
    )
    override = Path("configs/default_tandao2_glm5.yaml")
    override.write_text(yaml_text, encoding="utf-8")
    cfg.config_path = override

    logger = logging.getLogger("tandao2_glm5")
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    print(f"[{job_id}] resume=True 复用 analyzed.json，用 glm-5.2 重做 EDL + 渲染")
    result = job_mod.process_job(cfg, logger=logger, resume=True,
                                 model="glm-4.6v", use_edl=True)

    print()
    print("=== 结果 ===")
    print(f"status: {result.status}")
    print(f"final_video: {result.final_video}")
    print(f"edl: {result.edl}")
    print(f"cost: vision_calls={result.cost.vision_calls} duration={result.cost.duration_sec:.1f}s")

    if result.edl and result.edl.exists():
        edl = json.loads(result.edl.read_text(encoding="utf-8"))
        print()
        print("=== EDL 详情 ===")
        print(f"model used: {edl.get('model')}")
        print(f"narrative: {edl['narrative']}")
        print(f"expected_duration: {edl['expected_duration_sec']}s (target {edl['target_duration_sec']}s)")
        print(f"items ({len(edl['selected'])}):")
        for it in edl["selected"]:
            print(f"  {it['order']:>2}. {it['id']:<12} [{it['use_start']:.2f}-{it['use_end']:.2f}]={it['cut_duration']:.2f}s {it['story_role_assigned']:<10} reason={it['reason']}")


if __name__ == "__main__":
    main()
