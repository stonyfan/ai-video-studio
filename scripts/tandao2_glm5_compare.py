"""
离线对比：用同一份候选池（已存在 jobs/tandao2_edl/work/candidate_pool.json）
喂给 glm-5.2 做 EDL 规划，对比 glm-4-plus 的输出。

不重跑视觉分析（省 ~17 分钟），只测 EDL 规划这一步模型差异。
"""
from __future__ import annotations
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("ZHIPU_API_KEY", "253e42f83cff402b8e2c2825dbee3310.qRIdGGx9MvzIG9IC")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from video_worker import edl_planner
from video_worker.providers.glm import GLMProvider
from video_worker.validators import (
    JobConfig, CandidatePool, AnalyzedScene, CandidateClip, Style, Provider,
)


def load_pool(job_dir: Path) -> CandidatePool:
    """从 candidate_pool.json 重建 CandidatePool 对象。"""
    pool_data = json.loads((job_dir / "work" / "candidate_pool.json").read_text(encoding="utf-8"))

    def to_clip(d: dict) -> CandidateClip:
        a_data = d["analyzed"]
        a = AnalyzedScene(**a_data)
        return CandidateClip(
            id=d["id"], status=d["status"], score=d["score"],
            reason=d["reason"], analyzed=a,
        )

    return CandidatePool(
        job_id=pool_data["job_id"],
        created_at=pool_data["created_at"],
        keep=[to_clip(c) for c in pool_data["keep"]],
        maybe=[to_clip(c) for c in pool_data["maybe"]],
        discard=[to_clip(c) for c in pool_data["discard"]],
        rule_summary=pool_data.get("rule_summary", {}),
    )


def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    logger = logging.getLogger("glm5_compare")

    job_dir = Path("jobs/tandao2_edl")
    pool = load_pool(job_dir)
    print(f"候选池加载: keep={len(pool.keep)} maybe={len(pool.maybe)} discard={len(pool.discard)}")

    # 加载之前的 glm-4-plus 结果
    edl_4plus = json.loads((job_dir / "work" / "edl.json").read_text(encoding="utf-8"))

    cfg = JobConfig(
        job_id="tandao2_glm5_compare",
        input_path=r"C:\Users\86150\Downloads\檀道2",
        platform="general",
        style=Style.NARRATIVE,
        target_duration=30,
        provider=Provider.GLM,
        work_root="jobs",
        ffmpeg_path="ffmpeg",
        config_path=Path("configs/default.yaml"),
        natural_language_request="做成有故事感的檀道宣传片，展现从原料到成品的工匠精神",
    )

    # === 用 glm-5.2 做 EDL ===
    provider = GLMProvider(model="glm-5.2", timeout_sec=180)
    print(f"\n=== 用 glm-5.2 规划 EDL ===")
    try:
        edl_5 = edl_planner.plan_edl(
            pool, cfg, provider,
            target_duration=30,
            max_candidates=40,
            tolerance=0.2,
            fallback_models=[],  # 不 fallback，强制 glm-5.2
            prompts_path=Path("configs/prompts.yaml"),
            logger=logger,
        )
    except Exception as e:
        print(f"glm-5.2 EDL 失败: {e}")
        return

    # === 对比 ===
    print(f"\n{'='*60}")
    print(f"glm-4-plus（之前）: {len(edl_4plus['selected'])} 段, 总时长 {edl_4plus['expected_duration_sec']}s, model={edl_4plus['model']}")
    print(f"glm-5.2 （现在）  : {len(edl_5.selected)} 段, 总时长 {edl_5.expected_duration_sec}s, model={edl_5.model}")

    # 加载 analyzed 拿 main_objects（用于主体多样性对比）
    analyzed_list = json.loads((job_dir / "work" / "analyzed.json").read_text(encoding="utf-8"))
    obj_map = {a["id"]: a.get("main_objects", []) for a in analyzed_list}
    moment_map = {a["id"]: a.get("best_moment", "") for a in analyzed_list}
    role_map = {a["id"]: a.get("story_role", "") for a in analyzed_list}

    def show_edl(label: str, items: list, model_name: str):
        print(f"\n--- {label}（{model_name}）---")
        prev_objs = None
        max_run = 1
        run_len = 1
        for it in items:
            iid = it["id"] if isinstance(it, dict) else it.id
            use_start = it["use_start"] if isinstance(it, dict) else it.use_start
            use_end = it["use_end"] if isinstance(it, dict) else it.use_end
            cut_dur = it["cut_duration"] if isinstance(it, dict) else it.cut_duration
            role = it["story_role_assigned"] if isinstance(it, dict) else it.story_role_assigned
            reason = it.get("reason", "") if isinstance(it, dict) else it.reason
            objs = frozenset(obj_map.get(iid, []))
            if objs and objs == prev_objs:
                run_len += 1
                max_run = max(max_run, run_len)
            else:
                run_len = 1
            prev_objs = objs
            objs_str = "/".join(sorted(objs)) if objs else "(none)"
            moment = moment_map.get(iid, "")[:20]
            print(f"  {it['order'] if isinstance(it, dict) else it.order:>2}. {iid:<12} [{use_start:.1f}-{use_end:.1f}]={cut_dur:.2f}s {role:<10} objs={objs_str:<25} moment={moment} reason={reason}")
        print(f"  最长连续同主体 run: {max_run}")

    show_edl("glm-4-plus", edl_4plus["selected"], edl_4plus["model"])
    show_edl("glm-5.2", [it.model_dump() for it in edl_5.selected], edl_5.model)

    # 故事弧完整性对比
    def check_arc(items: list) -> dict:
        first_roles = {(it["story_role_assigned"] if isinstance(it, dict) else it.story_role_assigned) for it in items[:2]}
        last_roles = {(it["story_role_assigned"] if isinstance(it, dict) else it.story_role_assigned) for it in items[-2:]}
        return {
            "开头含 opening/hook": bool(first_roles & {"opening", "hook"}),
            "结尾含 ending": bool(last_roles & {"ending"}),
        }

    print(f"\n--- 故事弧对比 ---")
    arc_4p = check_arc(edl_4plus["selected"])
    arc_5 = check_arc([it.model_dump() for it in edl_5.selected])
    print(f"glm-4-plus: {arc_4p}")
    print(f"glm-5.2   : {arc_5}")

    # 用到的源视频覆盖
    def src_coverage(items: list) -> set:
        return {(it["id"] if isinstance(it, dict) else it.id).split("_")[0] for it in items}

    print(f"\n--- 源视频覆盖 ---")
    print(f"glm-4-plus 用到 {len(src_coverage(edl_4plus['selected']))} 个源: {sorted(src_coverage(edl_4plus['selected']))}")
    print(f"glm-5.2    用到 {len(src_coverage([it.model_dump() for it in edl_5.selected]))} 个源: {sorted(src_coverage([it.model_dump() for it in edl_5.selected]))}")

    # 保存 glm-5.2 结果
    out_path = job_dir / "work" / "edl_glm5_2.json"
    out_path.write_text(
        json.dumps(edl_5.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nglm-5.2 EDL 已存: {out_path}")


if __name__ == "__main__":
    main()
