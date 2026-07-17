"""
檀道2 EDL 真实测试：跑 use_edl=True 全流程，验证 Phase 14.5 三层加固。
- prompt BAD/GOOD 例子生效（主体多样性）
- _validate_quality 校验
- 模型 fallback（glm-4.6v → glm-4-plus）
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
    if job_dir.exists():
        import shutil
        shutil.rmtree(job_dir)

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

    # 用一份带 edl.enabled=true 的 config override
    cfg_path = Path("configs/default.yaml")
    import yaml
    yaml_text = cfg_path.read_text(encoding="utf-8")
    yaml_text = yaml_text.replace("edl:\n  enabled: false", "edl:\n  enabled: true")
    override = Path("configs/default_tandao2_edl.yaml")
    override.write_text(yaml_text, encoding="utf-8")
    cfg.config_path = override

    logger = logging.getLogger("tandao2_edl")
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    print(f"[{job_id}] 启动 EDL 全流程测试（Phase 14.5 加固版）")
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
        print(f"model used: {edl.get('model')}")
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

    # EDL 主体多样性分析（验证 prompt 加固是否生效）
    if result.edl and result.edl.exists():
        edl = json.loads(result.edl.read_text(encoding="utf-8"))
        # 加载 analyzed 拿 main_objects
        analyzed_path = Path("jobs") / job_id / "work" / "analyzed.json"
        if analyzed_path.exists():
            analyzed_list = json.loads(analyzed_path.read_text(encoding="utf-8"))
            obj_map = {a["id"]: a.get("main_objects", []) for a in analyzed_list}
            print()
            print("=== 主体多样性检查 ===")
            prev_objs = None
            run_len = 1
            max_run = 1
            for i, it in enumerate(edl["selected"]):
                objs = frozenset(obj_map.get(it["id"], []))
                if objs and objs == prev_objs:
                    run_len += 1
                    max_run = max(max_run, run_len)
                else:
                    run_len = 1
                print(f"  段 {it['order']}: {sorted(objs)}")
                prev_objs = objs
            print(f"  最长连续同主体 run: {max_run}")
            if max_run >= 3:
                print(f"  [FAIL] 检测到 {max_run} 连续同主体（应 ≤2）")
            else:
                print(f"  [OK] 主体多样性符合规则")


if __name__ == "__main__":
    main()
