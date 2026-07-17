"""
v2 多变体生成：重跑 vision（用最新 prompts.yaml）+ 10 个 variant。

与 v1 的区别：
- 复用源 job 的 scenes + frames_seq + clips（不重跑 preprocess / scene_detect / frame_extract）
- 重跑 vision_analyze.analyze（让新 prompts 的【分数梯度】+【转场无效】规则生效）
- 重跑 candidate_pool.classify（让 discard_actions=["walking"] 生效）
- 跑 10 个 variant

预期：
- 分数真的有梯度（1-9 分布）
- walking 段被 discard
- role 有 opening/process/climax/ending 分布
- 10 个 variant 段差异更明显（因为分数有梯度，LLM 编排才能真的差异化）

用法:
  python scripts/rerun_vision_multi.py \
    --source-job job_mrm5ifn0eodv \
    --target-job job_v2_xusong \
    --variants 10
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from video_worker import storyboard, render, timeline_dedup, vision_analyze, config, candidate_pool
from video_worker.validators import (
    JobConfig, Platform, Style, Provider, AnalyzedScene, Scene, CandidatePool,
)


VARIANT_STYLE_HINTS = {
    1: "",
    2: "动作密集段优先，climax 集中在中段，每段 0.8-1.0s 短切",
    3: "色彩/构图丰富段优先，climax 分散，每段 1.2-1.5s 长放",
    4: "opening 标志性广角优先，climax 后置",
    5: "对称构图 + 居中主体优先",
    6: "运镜动态段优先（推拉摇移）",
    7: "特写镜头优先，弱化全景",
    8: "全景建立画面优先，弱化特写",
    9: "高 visual_quality 段优先，舍弃所有中等画质",
    10: "高 motion_score 段优先，舍弃静态",
}


def get_style_hint(idx: int) -> str:
    return VARIANT_STYLE_HINTS.get(idx, "")


def rebuild_frames_map(frames_seq_dir: Path, scenes: list[Scene]) -> dict[str, list[Path]]:
    """从 frames_seq/ 目录扫描重建 {scene_id: [frame_path, ...]}"""
    frames_map: dict[str, list[Path]] = {}
    for sc in scenes:
        prefix = f"{sc.id}_f"
        frames = sorted(frames_seq_dir.glob(f"{prefix}*.jpg"))
        if frames:
            frames_map[sc.id] = frames
    return frames_map


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-job", required=True,
                    help="提供 scenes.json + frames_seq 的源 job")
    ap.add_argument("--analyzed-source-job", default=None,
                    help="analyzed.json 来源 job（不传 = source-job，传 = 用别的 job 的 analyzed）")
    ap.add_argument("--target-job", required=True)
    ap.add_argument("--variants", type=int, default=10)
    ap.add_argument("--work-root",
                    default=r"C:\Users\86150\AppData\Roaming\ai-video-studio-desktop\jobs")
    ap.add_argument("--duration", type=int, default=30)
    ap.add_argument("--platform", default="xhs")
    ap.add_argument("--style", default="ambiance")
    ap.add_argument("--orchestration-mode", default="default",
                    choices=["timeline", "llm", "default"])
    ap.add_argument("--provider", default="doubao-agent-plan")
    ap.add_argument("--model", default="doubao-seed-2.0-pro")
    ap.add_argument("--skill", default="none")
    ap.add_argument("--vertical", default="food",
                    help="prompts 的 vertical（default/travel/food/beauty）")
    ap.add_argument("--ffmpeg",
                    default=r"D:\ai-video-studio\dist\video-worker\_internal\tools\ffmpeg.exe")
    ap.add_argument("--config-yaml",
                    default=r"D:\ai-video-studio\dist\video-worker\_internal\configs\default.yaml")
    ap.add_argument("--prompts-path",
                    default=r"D:\ai-video-studio\configs\prompts.yaml",
                    help="用本地最新 prompts.yaml（不走 desktop 缓存）")
    ap.add_argument("--max-workers", type=int, default=5)
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--skip-vision", action="store_true",
                    help="跳过 vision 重跑（debug 用）")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("rerun_v2")

    work_root = Path(args.work_root)
    src_dir = work_root / args.source_job
    tgt_dir = work_root / args.target_job
    if tgt_dir.exists():
        logger.warning(f"target_job 已存在，可能覆盖: {tgt_dir}")
    (tgt_dir / "output").mkdir(parents=True, exist_ok=True)
    (tgt_dir / "work").mkdir(parents=True, exist_ok=True)
    (tgt_dir / "logs").mkdir(parents=True, exist_ok=True)

    # === 1. 读源 job 的 scenes + frames_seq ===
    scenes_raw = json.loads((src_dir / "work" / "scenes.json").read_text(encoding="utf-8"))
    scenes = [Scene(**s) for s in scenes_raw]
    logger.info(f"读 scenes: {len(scenes)} 条")

    # 修正 scenes 里的 src 路径（指向源 job 的 clips）
    # frames_map 也要从源 job 读
    frames_map = rebuild_frames_map(src_dir / "work" / "frames_seq", scenes)
    logger.info(f"重建 frames_map: {len(frames_map)} scene（共 {sum(len(v) for v in frames_map.values())} 帧）")

    # === 2. 加载 yaml + provider ===
    yaml_cfg = config.load_yaml(Path(args.config_yaml))
    p_cfg = config.get_platform_config(yaml_cfg, Platform(args.platform))
    r_cfg = yaml_cfg.get("render", {})

    if args.api_key:
        api_key = args.api_key
    else:
        desktop_cfg_path = Path(os.path.expanduser("~")) / "AppData/Roaming/ai-video-studio-desktop/config.json"
        desktop_cfg = json.loads(desktop_cfg_path.read_text(encoding="utf-8"))
        dk = desktop_cfg["provider_keys"]["doubao-agent-plan"]
        api_key = dk["key"]
        logger.info(f"用 desktop config 的 doubao-agent-plan key (model={dk.get('model')})")

    provider = vision_analyze.get_provider(
        args.provider, api_key=api_key, model=args.model,
        mode="direct", logger=logger,
    )

    # === 3. 重跑 vision_analyze.analyze（用最新 prompts.yaml）===
    analyzed: list[AnalyzedScene] = []
    analyzed_source_dir = (work_root / args.analyzed_source_job) if args.analyzed_source_job else src_dir
    if not args.skip_vision:
        logger.info(f"=== 重跑 vision analyze (vertical={args.vertical}, "
                    f"prompts={args.prompts_path}, max_workers={args.max_workers}) ===")
        t0 = time.time()
        analyzed = vision_analyze.analyze(
            scenes, frames_map, provider, tgt_dir,
            vertical=args.vertical,
            logger=logger,
            max_workers=args.max_workers,
            prompts_path=Path(args.prompts_path),
        )
        logger.info(f"vision 完成: {len(analyzed)} 段 / {time.time()-t0:.1f}s")
    else:
        # skip_vision: 从 analyzed_source_job 读已生成的 analyzed.json
        logger.warning(f"skip_vision=True：读 {analyzed_source_dir} 的 analyzed.json")
        analyzed = [AnalyzedScene(**a) for a in json.loads(
            (analyzed_source_dir / "work" / "analyzed.json").read_text(encoding="utf-8")
        )]

    # === 3.5 诊断分数分布 ===
    from collections import Counter
    h_dist = Counter(a.highlight_score for a in analyzed)
    role_dist = Counter(a.story_role for a in analyzed)
    act_dist = Counter(a.action_type for a in analyzed)
    bad_count = sum(1 for a in analyzed if a.bad_reason)
    logger.info(f"=== 诊断 ===")
    logger.info(f"highlight_score 分布: {dict(sorted(h_dist.items()))}")
    logger.info(f"story_role 分布: {dict(role_dist.most_common())}")
    logger.info(f"action_type 分布: {dict(act_dist.most_common())}")
    logger.info(f"bad_reason 非空: {bad_count}/{len(analyzed)}")

    # === 4. 重跑 candidate_pool.classify（让 discard_actions 生效）===
    logger.info(f"=== candidate_pool 分类 ===")
    pool_path = tgt_dir / "work" / "candidate_pool.json"
    try:
        pool = candidate_pool.classify(analyzed, job_id=args.target_job, logger=logger)
        keep_ids = {c.id for c in pool.keep}
        maybe_ids = {c.id for c in pool.maybe}
        discard_ids = {c.id for c in pool.discard}
        logger.info(f"  keep={len(pool.keep)} maybe={len(pool.maybe)} discard={len(pool.discard)}")
        pool_path.write_text(pool.model_dump_json(indent=2), encoding="utf-8")
    except Exception as e:
        logger.exception(f"candidate_pool 失败，退回全 maybe: {e}")
        keep_ids = set()
        maybe_ids = {a.id for a in analyzed}
        discard_ids = set()

    # 用 keep+maybe 作为编排候选池（discard 真的丢）
    candidates = [a for a in analyzed if a.id not in discard_ids]
    logger.info(f"  编排候选: {len(candidates)} 段（discard 排除 {len(discard_ids)}）")

    # === 5. 读 creation_time ===
    src_cfg = json.loads((src_dir / "logs" / "job_config.json").read_text(encoding="utf-8"))
    input_path = src_cfg["input_path"]
    creation_times = timeline_dedup.read_src_creation_times(
        Path(input_path), Path(args.ffmpeg), logger=logger,
    )

    # === 6. skill snippet ===
    skill_snippet = ""
    if args.skill and args.skill.lower() not in ("auto", "none"):
        try:
            from video_worker.skill_loader import load_skill
            resolved = load_skill(args.skill)
            skill_snippet = resolved.full_prompt_block()
            logger.info(f"skill={resolved.name} snippet={len(skill_snippet)} 字")
        except Exception as e:
            logger.warning(f"skill 加载失败: {e}")

    # === 7. JobConfig ===
    cfg = JobConfig(
        job_id=args.target_job,
        input_path=Path(input_path),
        platform=Platform(args.platform),
        style=Style(args.style),
        target_duration=args.duration,
        provider=Provider(args.provider),
        work_root=work_root,
        ffmpeg_path=Path(args.ffmpeg),
        config_path=Path(args.config_yaml),
        orchestration_mode=args.orchestration_mode,
        skill=args.skill,
        variants=args.variants,
    )

    # === 8. variant 循环 ===
    cd_range = (0.8, 1.5)
    total = args.variants
    summary = []

    # 用 candidates（已排除 discard）替代 analyzed 传给 storyboard.plan
    # 但 render 仍需 analyzed 全量（按 id 查回）
    analyzed_dict = {a.id: a for a in analyzed}

    for v_idx in range(1, total + 1):
        style_hint = get_style_hint(v_idx)
        hint_label = style_hint[:40] + "..." if style_hint else "默认平衡"
        logger.info(f"=== variant {v_idx}/{total} (hint={hint_label}) ===")
        t0 = time.time()
        try:
            stages = None
            if args.orchestration_mode in ("llm", "default"):
                from video_worker.storyboard import _timeline_key, _source_id
                sorted_for_llm = sorted(candidates, key=lambda a: _timeline_key(a, creation_times))
                scenes_for_llm = [
                    {**a.model_dump(), "source_id": _source_id(a)}
                    for a in sorted_for_llm
                ]
                stages = timeline_dedup.cluster_by_timeline(
                    scenes_for_llm, provider, args.model, logger=logger,
                    skill_snippet=skill_snippet,
                    style_hint=style_hint,
                )
                logger.info(f"  cluster: {len(stages)} stages")

            board = storyboard.plan(
                candidates, cfg,
                target_duration=args.duration,
                cut_duration_range=cd_range,
                orchestration_mode=args.orchestration_mode,
                creation_times=creation_times,
                stages=stages,
                style_hint=style_hint,
                logger=logger,
            )
            logger.info(f"  plan: {len(board.selected)} 段 / {board.expected_duration_sec:.1f}s")

            sb_path = tgt_dir / "work" / f"storyboard_v{v_idx}.json"
            sb_path.write_text(
                json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

            mp4_name = f"final_v{v_idx}.mp4"
            v_final = render.render(
                board, analyzed, cfg, tgt_dir,
                color_grade=p_cfg.get("color_grade", "natural"),
                bgm_atempo=p_cfg.get("bgm_atempo", 1.0),
                ass_fontsize=p_cfg.get("ass", {}).get("fontsize", 30),
                ass_outline=p_cfg.get("ass", {}).get("outline", 2.5),
                ass_marginv=p_cfg.get("ass", {}).get("marginv", 100),
                crf=r_cfg.get("crf", 20),
                bgm_volume=r_cfg.get("bgm_volume", 0.85),
                fade_in=r_cfg.get("fade_in_sec", 1.0),
                fade_out=r_cfg.get("fade_out_sec", 1.5),
                xfade_dur=r_cfg.get("xfade_dur", 0.0),
                output_filename=mp4_name,
                logger=logger,
            )
            dt = time.time() - t0
            logger.info(f"  v{v_idx} done @ {v_final} ({dt:.1f}s)")
            summary.append({"idx": v_idx, "hint": style_hint, "path": str(v_final),
                            "n": len(board.selected), "dur": board.expected_duration_sec})
        except Exception as e:
            logger.exception(f"  v{v_idx} 失败: {e}")
            summary.append({"idx": v_idx, "hint": style_hint, "error": str(e)})

    # === 汇总 ===
    summary_path = tgt_dir / "logs" / "variants_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    logger.info(f"\n=== 汇总 ===")
    for s in summary:
        if "error" in s:
            logger.info(f"  v{s['idx']}: X {s['error'][:80]}")
        else:
            logger.info(f"  v{s['idx']}: {s['n']}段/{s['dur']:.1f}s -> {Path(s['path']).name}")


if __name__ == "__main__":
    main()
