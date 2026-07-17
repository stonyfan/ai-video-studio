"""
qd_p3 EDL 真实测试：跑 use_edl=True 全流程，对比 use_edl=False 的 storyboard 结果。
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
    job_id = "qd_p3_edl"
    job_dir = Path("jobs") / job_id
    if job_dir.exists():
        import shutil
        shutil.rmtree(job_dir)

    cfg = JobConfig(
        job_id=job_id,
        input_path=r"C:\Users\86150\Downloads\青岛",
        platform="general",
        style="narrative",
        target_duration=30,
        provider="glm",
        work_root="jobs",
        ffmpeg_path=str(resolve_ffmpeg(Path("tools/ffmpeg.exe"))),
        config_path=bundled_config(Path("configs/default.yaml")),
        natural_language_request="做成有故事感的青岛夜景视频",
    )

    # 用一份带 edl.enabled=true 的 config override
    cfg_path = Path("configs/default.yaml")
    # 复制 + 改 edl.enabled
    import yaml
    yaml_text = cfg_path.read_text(encoding="utf-8")
    yaml_text = yaml_text.replace("edl:\n  enabled: false", "edl:\n  enabled: true")
    override = Path("configs/default_edl.yaml")
    override.write_text(yaml_text, encoding="utf-8")
    cfg.config_path = override

    logger = logging.getLogger("qd_p3_edl")
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    print(f"[{job_id}] 启动 EDL 全流程测试")
    result = job_mod.process_job(cfg, logger=logger, resume=False,
                                 model="glm-4.6v", use_edl=True)

    print()
    print("=== 结果 ===")
    print(f"status: {result.status}")
    print(f"final_video: {result.final_video}")
    print(f"candidate_pool: {result.candidate_pool}")
    print(f"edl: {result.edl}")
    print(f"storyboard: {result.storyboard}")
    print(f"cost: vision_calls={result.cost.vision_calls} duration={result.cost.duration_sec:.1f}s")

    # 详细分析 EDL
    if result.edl and result.edl.exists():
        edl = json.loads(result.edl.read_text(encoding="utf-8"))
        print()
        print("=== EDL 详情 ===")
        print(f"narrative: {edl['narrative']}")
        print(f"expected_duration: {edl['expected_duration_sec']}s (target {edl['target_duration_sec']}s)")
        print(f"items ({len(edl['selected'])}):")
        for it in edl["selected"]:
            short_id = it["id"][-30:]
            print(f"  {it['order']:>2}. {short_id:<30} [{it['use_start']:.2f}-{it['use_end']:.2f}]={it['cut_duration']:.2f}s {it['story_role_assigned']:<10} reason={it['reason']}")

    # 候选池分析
    if result.candidate_pool and result.candidate_pool.exists():
        pool = json.loads(result.candidate_pool.read_text(encoding="utf-8"))
        print()
        print("=== 候选池 ===")
        print(f"keep={len(pool['keep'])} maybe={len(pool['maybe'])} discard={len(pool['discard'])}")
        print(f"规则: {pool['rule_summary']}")


if __name__ == "__main__":
    main()
