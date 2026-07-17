"""
手动生成 N 个变体 —— 复用源 job 的 analyzed.json + clips，绕开 process_job 1-5 步。
直接跑 variant 循环（cluster_by_timeline + storyboard.plan + render）。

用法:
  python scripts/gen_multi_variants.py \
    --source-job job_mrm5ifn0eodv \
    --target-job job_multi10_test \
    --variants 10

输出: <target_job>/output/final_v1.mp4 ... final_v{N}.mp4
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path

# 让 from video_worker import ... 能跑
sys.path.insert(0, str(Path(__file__).parent.parent))

from video_worker import storyboard, render, timeline_dedup, vision_analyze, config
from video_worker.validators import (
    JobConfig, Platform, Style, Provider, AnalyzedScene,
)


# 与 job.py 同步的 style hint 表
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-job", required=True, help="源 job_id（提供 analyzed.json + clips）")
    ap.add_argument("--target-job", required=True, help="新 job_id（输出位置）")
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
    ap.add_argument("--ffmpeg",
                    default=r"D:\ai-video-studio\dist\video-worker\_internal\tools\ffmpeg.exe")
    ap.add_argument("--config-yaml",
                    default=r"D:\ai-video-studio\dist\video-worker\_internal\configs\default.yaml")
    ap.add_argument("--api-key", default=None,
                    help="覆盖，默认从 desktop config.json 读")
    args = ap.parse_args()

    # 设置 logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("multi_variant")

    work_root = Path(args.work_root)
    src_dir = work_root / args.source_job
    tgt_dir = work_root / args.target_job
    if tgt_dir.exists():
        logger.warning(f"target_job 已存在，可能覆盖: {tgt_dir}")
    (tgt_dir / "output").mkdir(parents=True, exist_ok=True)
    (tgt_dir / "work").mkdir(parents=True, exist_ok=True)
    (tgt_dir / "logs").mkdir(parents=True, exist_ok=True)

    # === 读源 job 的 analyzed.json + job_config ===
    src_analyzed_path = src_dir / "work" / "analyzed.json"
    src_cfg_path = src_dir / "logs" / "job_config.json"
    logger.info(f"读 analyzed: {src_analyzed_path}")
    analyzed_raw = json.loads(src_analyzed_path.read_text(encoding="utf-8"))
    analyzed = [AnalyzedScene(**a) for a in analyzed_raw]
    logger.info(f"  → {len(analyzed)} 段")

    src_cfg = json.loads(src_cfg_path.read_text(encoding="utf-8"))
    input_path = src_cfg["input_path"]
    logger.info(f"  input_path: {input_path}")

    # === 加载 yaml 配置 ===
    yaml_cfg = config.load_yaml(Path(args.config_yaml))
    p_cfg = config.get_platform_config(yaml_cfg, Platform(args.platform))
    r_cfg = yaml_cfg.get("render", {})

    # === 读 doubao-agent-plan key ===
    if args.api_key:
        api_key = args.api_key
    else:
        desktop_cfg = json.loads(
            (Path(os.path.expanduser("~")) / "AppData/Roaming/ai-video-studio-desktop/config.json")
            .read_text(encoding="utf-8")
        ) if (os := __import__('os')) else None
        dk = desktop_cfg["provider_keys"]["doubao-agent-plan"]
        api_key = dk["key"]
        logger.info(f"用 desktop config 的 doubao-agent-plan key（model={dk.get('model')}）")

    # === 建 provider ===
    provider = vision_analyze.get_provider(
        args.provider,
        api_key=api_key,
        model=args.model,
        mode="direct",
        logger=logger,
    )

    # === 读 creation_time ===
    creation_times = timeline_dedup.read_src_creation_times(
        Path(input_path), Path(args.ffmpeg), logger=logger,
    )

    # === 加载 skill snippet ===
    skill_snippet = ""
    if args.skill and args.skill.lower() not in ("auto", "none"):
        try:
            from video_worker.skill_loader import load_skill
            resolved = load_skill(args.skill)
            skill_snippet = resolved.full_prompt_block()
            logger.info(f"skill={resolved.name} snippet={len(skill_snippet)} 字")
        except Exception as e:
            logger.warning(f"skill 加载失败: {e}")

    # === JobConfig 给 storyboard.plan 用 ===
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

    # === variant 循环 ===
    cd_range = (0.8, 1.5)
    total = args.variants
    summary = []
    for v_idx in range(1, total + 1):
        style_hint = get_style_hint(v_idx)
        hint_label = style_hint[:40] + "..." if style_hint else "默认平衡"
        logger.info(f"=== variant {v_idx}/{total} (hint={hint_label}) ===")
        t0 = time.time()
        try:
            # LLM 聚类
            stages = None
            if args.orchestration_mode in ("llm", "default"):
                from video_worker.storyboard import _timeline_key, _source_id
                sorted_for_llm = sorted(analyzed, key=lambda a: _timeline_key(a, creation_times))
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

            # storyboard
            board = storyboard.plan(
                analyzed, cfg,
                target_duration=args.duration,
                cut_duration_range=cd_range,
                orchestration_mode=args.orchestration_mode,
                creation_times=creation_times,
                stages=stages,
                logger=logger,
            )
            logger.info(f"  plan: {len(board.selected)} 段 / {board.expected_duration_sec:.1f}s")

            sb_path = tgt_dir / "work" / f"storyboard_v{v_idx}.json"
            sb_path.write_text(
                json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

            # render
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
            logger.info(f"  ✓ v{v_idx} done @ {v_final} ({dt:.1f}s)")
            summary.append({"idx": v_idx, "hint": style_hint, "path": str(v_final),
                            "n": len(board.selected), "dur": board.expected_duration_sec})
        except Exception as e:
            logger.exception(f"  ✗ v{v_idx} 失败: {e}")
            summary.append({"idx": v_idx, "hint": style_hint, "error": str(e)})

    # === 汇总 ===
    summary_path = tgt_dir / "logs" / "variants_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    logger.info(f"\n=== 汇总（写入 {summary_path}）===")
    for s in summary:
        if "error" in s:
            logger.info(f"  v{s['idx']}: ✗ {s['error'][:80]}")
        else:
            logger.info(f"  v{s['idx']}: ✓ {s['n']}段/{s['dur']:.1f}s → {Path(s['path']).name}")


if __name__ == "__main__":
    main()
