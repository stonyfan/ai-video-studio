"""
CLI: python -m video_worker --input <dir> --platform douyin [--duration 30]
"""
from __future__ import annotations
import argparse
import sys
import uuid
from pathlib import Path

from .validators import JobConfig, Platform, Style, Provider
from .job import process_job


def main():
    parser = argparse.ArgumentParser(
        prog="video_worker",
        description="AI 视频智能剪辑 worker",
    )
    parser.add_argument("--input", "-i", required=True, type=Path,
                        help="素材目录或单个视频文件")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="输出文件路径（默认 jobs/<id>/output/final.mp4）")
    parser.add_argument("--platform", "-p",
                        choices=[p.value for p in Platform],
                        default="general")
    parser.add_argument("--style", "-s",
                        choices=[s.value for s in Style],
                        default="fast_cut")
    parser.add_argument("--duration", "-d", type=int, default=30,
                        help="目标时长（秒）")
    parser.add_argument("--bgm", type=Path, default=None,
                        help="BGM 文件路径")
    parser.add_argument("--provider",
                        choices=[p.value for p in Provider],
                        default="zai")
    parser.add_argument("--job-id", default=None,
                        help="自定义 job_id（默认自动生成）")
    parser.add_argument("--work-root", type=Path, default=Path("jobs"))
    parser.add_argument("--ffmpeg", type=Path, default=Path("tools/ffmpeg.exe"))
    parser.add_argument("--config", type=Path, default=Path("configs/default.yaml"))
    parser.add_argument("--skip-vision", action="store_true",
                        help="跳过 AI 视觉分析（用默认值）")
    parser.add_argument("--skip-render", action="store_true",
                        help="只到 storyboard，不渲染")

    args = parser.parse_args()

    job_id = args.job_id or f"job_{uuid.uuid4().hex[:8]}"

    cfg = JobConfig(
        job_id=job_id,
        input_path=args.input,
        output_path=args.output,
        platform=Platform(args.platform),
        style=Style(args.style),
        target_duration=args.duration,
        bgm_path=args.bgm,
        provider=Provider(args.provider),
        work_root=args.work_root,
        ffmpeg_path=args.ffmpeg,
        config_path=args.config,
    )

    result = process_job(cfg, skip_vision=args.skip_vision, skip_render=args.skip_render)
    print(f"\n=== 结果 ===")
    print(f"job_id: {result.job_id}")
    print(f"status: {result.status.value}")
    print(f"final:  {result.final_video}")
    print(f"log:    {result.log}")
    print(f"duration: {result.cost.duration_sec:.1f}s")

    sys.exit(0 if result.status.value == "completed" else 1)


if __name__ == "__main__":
    main()
