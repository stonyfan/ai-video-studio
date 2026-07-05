"""
process_job 主入口：JSON in → JSON out
"""
from __future__ import annotations
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .validators import JobConfig, JobResult, JobStatus, ErrorInfo, CostBreakdown
from . import storage, progress, config, media_scan, preprocess, scene_detect
from . import frame_extract, vision_analyze, storyboard, render


def process_job(config_in: JobConfig,
                provider=None,
                logger: Optional[logging.Logger] = None,
                skip_vision: bool = False,
                 skip_render: bool = False) -> JobResult:
    """
    单一入口。

    provider: 实现 analyze_image(image_path, prompt) -> str 的对象
              None 时按 config.provider 取默认（生产用）/ Mock（测试用）
    skip_vision: True 时跳过 AI 分析（用默认值填充）
    skip_render: True 时只到 storyboard，不渲染
    """
    started = datetime.now().isoformat(timespec="seconds")

    # 加载 YAML 配置
    yaml_cfg = config.load_yaml(config_in.config_path or Path("configs/default.yaml"))

    # 应用平台覆盖
    config.apply_platform_overrides(config_in, yaml_cfg)

    # 创建任务目录
    ok, free_gb = storage.check_disk_space(config_in.work_root, min_gb=1.0)
    if not ok:
        raise RuntimeError(f"磁盘空间不足: {free_gb:.1f} GB")
    job_dir = storage.create_job_dir(config_in.job_id, config_in.work_root, clean_if_exists=True)

    # 配置 logger
    if logger is None:
        logger = storage.setup_logger(config_in.job_id, job_dir)
    logger.info(f"=== 开始 job {config_in.job_id} ===")
    logger.info(f"input={config_in.input_path} platform={config_in.platform.value} "
                f"style={config_in.style.value} target={config_in.target_duration}s")

    # 配置 progress
    progress.configure_work_root(config_in.work_root)
    progress.report(config_in.job_id, JobStatus.CREATED, work_root=config_in.work_root)

    error = None
    final_video = None
    board_path = None
    vision_calls = 0
    try:
        # === 1. 扫描素材 ===
        logger.info("[1/7] 扫描素材")
        clips_src = media_scan.scan_videos(config_in.input_path, logger)
        progress.report(config_in.job_id, JobStatus.CREATED, work_root=config_in.work_root)

        # === 2. 预处理（重编码）===
        logger.info("[2/7] 重编码标准化")
        p_cfg = config.get_platform_config(yaml_cfg, config_in.platform)
        resolution = tuple(p_cfg.get("resolution", [720, 1280]))
        fps = p_cfg.get("fps", 25)
        clips = preprocess.normalize(clips_src, job_dir, config_in,
                                     resolution=resolution, fps=fps,
                                     ffmpeg_path=config_in.ffmpeg_path, logger=logger)
        if not clips:
            raise RuntimeError("重编码后无可用视频")
        progress.report(config_in.job_id, JobStatus.PREPROCESSED, work_root=config_in.work_root)

        # === 3. 场景切分 ===
        logger.info("[3/7] 场景切分")
        sd_cfg = yaml_cfg.get("scene_detect", {})
        scenes = scene_detect.split_scenes(
            clips, job_dir, config_in.ffmpeg_path,
            threshold=sd_cfg.get("threshold", 27.0),
            min_len_sec=sd_cfg.get("min_len_sec", 0.4),
            logger=logger,
        )
        if not scenes:
            raise RuntimeError("场景切分为空")

        # === 4. 抽帧 + 三联图 ===
        logger.info("[4/7] 三联图生成")
        triplets = frame_extract.make_triplets(scenes, job_dir, config_in.ffmpeg_path, logger)
        progress.report(config_in.job_id, JobStatus.TRIPLETS_READY, work_root=config_in.work_root)

        # === 5. AI 视觉分析 ===
        logger.info(f"[5/7] AI 视觉分析 (provider={config_in.provider.value}, skip={skip_vision})")
        if skip_vision:
            # 用默认值填充
            from .validators import AnalyzedScene
            analyzed = [
                AnalyzedScene(
                    id=sc.id, src=sc.src, start=sc.start, end=sc.end, dur=sc.dur,
                    best_frame="mid", cut_duration=p_cfg.get("cut_duration", 1.0),
                    best_moment="", main_object="", action_type="unknown",
                ) for sc in scenes
            ]
        else:
            if provider is None:
                provider = vision_analyze.get_provider(config_in.provider.value)
            analyzed = vision_analyze.analyze(scenes, triplets, provider, job_dir, logger)
            vision_calls = len(analyzed)
        progress.report(config_in.job_id, JobStatus.ANALYZED, work_root=config_in.work_root)

        # === 6. 编排 ===
        logger.info("[6/7] storyboard 编排")
        # 暂不接 BGM 节拍（BGM 在 render 阶段才用）
        board = storyboard.plan(analyzed, config_in, target_duration=config_in.target_duration,
                                logger=logger)
        board_path = storyboard.save_storyboard(board, job_dir)
        progress.report(config_in.job_id, JobStatus.PLANNED, work_root=config_in.work_root)

        # === 7. 渲染 ===
        if skip_render:
            logger.info("[7/7] skip_render=True，跳过渲染")
        else:
            logger.info("[7/7] FFmpeg 渲染")
            r_cfg = yaml_cfg.get("render", {})
            final_video = render.render(
                board, analyzed, config_in, job_dir,
                color_grade=p_cfg.get("color_grade", "natural"),
                bgm_atempo=p_cfg.get("bgm_atempo", 1.0),
                ass_fontsize=p_cfg.get("ass", {}).get("fontsize", 30),
                ass_outline=p_cfg.get("ass", {}).get("outline", 2.5),
                ass_marginv=p_cfg.get("ass", {}).get("marginv", 100),
                crf=r_cfg.get("crf", 20),
                bgm_volume=r_cfg.get("bgm_volume", 0.85),
                fade_in=r_cfg.get("fade_in_sec", 1.0),
                fade_out=r_cfg.get("fade_out_sec", 1.5),
                logger=logger,
            )

        progress.report(config_in.job_id, JobStatus.COMPLETED, work_root=config_in.work_root)
        status = JobStatus.COMPLETED

    except Exception as e:
        logger.exception(f"job 失败: {e}")
        error = ErrorInfo(stage="unknown", code=type(e).__name__, message=str(e))
        progress.report(config_in.job_id, JobStatus.FAILED,
                        error={"code": error.code, "message": error.message},
                        work_root=config_in.work_root)
        status = JobStatus.FAILED

    finished = datetime.now().isoformat(timespec="seconds")
    duration = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
    cost = CostBreakdown(vision_calls=vision_calls, duration_sec=duration)

    result = JobResult(
        job_id=config_in.job_id, status=status,
        final_video=final_video, storyboard=board_path,
        log=storage.get_log_path(job_dir),
        cost=cost, error=error,
        started_at=started, finished_at=finished,
    )

    # 持久化 result
    (job_dir / "logs" / "result.json").write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(f"=== job 结束 status={status.value} duration={duration:.1f}s ===")
    return result
