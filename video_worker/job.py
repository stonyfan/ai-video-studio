"""
process_job 主入口：JSON in → JSON out
"""
from __future__ import annotations
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from .validators import JobConfig, JobResult, JobStatus, ErrorInfo, CostBreakdown, Provider
from . import storage, progress, config, media_scan, preprocess, scene_detect
from . import frame_extract, vision_analyze, storyboard, render, candidate_pool, edl_planner
from . import timeline_dedup
from .validators import VariantResult


# Phase 17：多变体风格偏移表
# 注入 cluster_by_timeline 的 style_hint，让 LLM 在 stage 主题/representative 选择上偏向该风格
VARIANT_STYLE_HINTS = {
    1: "",  # 默认平衡（与单视频任务等价）
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


def _get_style_hint(idx: int) -> str:
    return VARIANT_STYLE_HINTS.get(idx, "")


def process_job(config_in: JobConfig,
                provider=None,
                api_key: Optional[str] = None,
                model: Optional[str] = None,
                mode: str = "direct",
                auth_token: Optional[str] = None,
                proxy_base_url: Optional[str] = None,
                logger: Optional[logging.Logger] = None,
                skip_vision: bool = False,
                skip_render: bool = False,
                skip_auth: bool = False,
                resume: bool = False,
                use_edl: bool = False,
                prompts_path: Optional[Path] = None) -> JobResult:
    """
    单一入口。

    provider: 实现 analyze_image(image_path, prompt) -> str 的对象
              None 时按 config.provider 取默认（生产用）/ Mock（测试用）
    api_key: A 模式直连时用的 provider API key（覆盖环境变量）
    model: 模型名（如 qwen-vl-plus）
    mode: direct（A 模式直连）/ proxy（C 模式预留）
    auth_token: proxy 模式用的 JWT
    skip_vision: True 时跳过 AI 分析（用默认值填充）
    skip_render: True 时只到 storyboard，不渲染
    skip_auth: 跳过登录态检查（开发/测试用）
    resume: True 时保留现有 job_dir，已有中间产物（preprocess/scene/analyze）会跳过
    use_edl: True 时启用 AI EDL 规划（需 yaml edl.enabled=true + provider=glm；失败 fallback storyboard）
    prompts_path: 自定义 prompts.yaml 路径（Phase 10 后端动态下发；None 用 bundled 默认）
    """
    started = datetime.now().isoformat(timespec="seconds")

    # Phase 10: prompts signature 用于 resume 时判断 prompt 是否变更
    prompts_sig = os.environ.get("WORKER_PROMPTS_SIG", "bundled")
    effective_prompts_path = prompts_path or vision_analyze.PROMPTS_DEFAULT_PATH

    # 加载 YAML 配置
    yaml_cfg = config.load_yaml(config_in.config_path or Path("configs/default.yaml"))

    # 应用平台覆盖
    config.apply_platform_overrides(config_in, yaml_cfg)

    # 创建任务目录
    ok, free_gb = storage.check_disk_space(config_in.work_root, min_gb=1.0)
    if not ok:
        raise RuntimeError(f"磁盘空间不足: {free_gb:.1f} GB")
    job_dir = storage.create_job_dir(
        config_in.job_id, config_in.work_root,
        clean_if_exists=not resume,
    )

    # 持久化任务配置（resume / 失败重试用）
    # resume 模式下不要覆盖，保留首次启动时的参数
    cfg_path = job_dir / "logs" / "job_config.json"
    if not cfg_path.exists():
        cfg_text = config_in.model_dump_json(indent=2)
        # 在 JSON 里追加 prompts_signature（不污染 JobConfig schema）
        try:
            cfg_obj = json.loads(cfg_text)
            cfg_obj["prompts_signature"] = prompts_sig
            cfg_text = json.dumps(cfg_obj, ensure_ascii=False, indent=2)
        except Exception:
            pass
        cfg_path.write_text(cfg_text, encoding="utf-8")
    else:
        # resume：比对 prompts_signature，不一致则废 analyzed.json
        try:
            old_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            old_sig = old_cfg.get("prompts_signature")
            if old_sig and old_sig != prompts_sig:
                analyzed_path = job_dir / "work" / "analyzed.json"
                if analyzed_path.exists():
                    if logger is None:
                        logger = storage.setup_logger(config_in.job_id, job_dir)
                    logger.warning(
                        f"[resume] prompts_signature 变更 (old={old_sig} new={prompts_sig})，"
                        f"废 analyzed.json 强制重分析"
                    )
                    analyzed_path.unlink()
        except Exception as e:
            if logger is None:
                logger = storage.setup_logger(config_in.job_id, job_dir)
            logger.warning(f"[resume] 检查 prompts_signature 失败: {e}")

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
    pool_path = None
    edl_path = None
    used_edl = False
    variant_results: list = []
    vision_calls = 0
    narrative_text: Optional[str] = None
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
        # 横屏转竖屏策略
        pp_cfg = yaml_cfg.get("preprocess", {})
        strategy = pp_cfg.get("resize_strategy", "blur_background")
        blur_sigma = pp_cfg.get("blur_sigma", 25.0)
        clips = preprocess.normalize(clips_src, job_dir, config_in,
                                     resolution=resolution, fps=fps,
                                     strategy=strategy, blur_sigma=blur_sigma,
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
            max_scene_len_sec=sd_cfg.get("max_scene_len_sec", 12.0),
            logger=logger,
        )
        if not scenes:
            raise RuntimeError("场景切分为空")

        # === 4. 抽帧 + 多帧序列 ===
        logger.info("[4/7] 多帧序列生成")
        fe_cfg = yaml_cfg.get("frame_extract", {})
        frames_map, analysis_scenes = frame_extract.make_frames_batch(
            scenes, job_dir, config_in.ffmpeg_path, logger=logger,
        )
        progress.report(config_in.job_id, JobStatus.TRIPLETS_READY, work_root=config_in.work_root)

        # === 5. AI 视觉分析 ===
        logger.info(f"[5/7] AI 视觉分析 (provider={config_in.provider.value}, skip={skip_vision}, mode={mode})")
        if skip_vision:
            # 用默认值填充（用 analysis_scenes，C 拆出的子区间也要填）
            from .validators import AnalyzedScene
            analyzed = [
                AnalyzedScene(
                    id=sc.id, src=sc.src, start=sc.start, end=sc.end, dur=sc.dur,
                    best_frame="mid", cut_duration=p_cfg.get("cut_duration", 1.0),
                    best_moment="", main_object="", action_type="unknown",
                ) for sc in analysis_scenes
            ]
        else:
            if provider is None:
                provider = vision_analyze.get_provider(
                    config_in.provider.value,
                    api_key=api_key,
                    model=model,
                    mode=mode,
                    auth_token=auth_token,
                    proxy_base_url=proxy_base_url,
                    logger=logger,
                )
            analyzed = vision_analyze.analyze(analysis_scenes, frames_map, provider, job_dir,
                                              logger=logger, prompts_path=effective_prompts_path)
            vision_calls = len(analyzed)
        progress.report(config_in.job_id, JobStatus.ANALYZED, work_root=config_in.work_root)

        # === 5.5 候选池分流（Phase 14）===
        logger.info("[5.5/7] 候选池分流")
        cp_cfg = yaml_cfg.get("candidate_pool", {})
        pool = candidate_pool.classify(
            analyzed, rules=cp_cfg, job_id=config_in.job_id, logger=logger,
        )
        pool_path = candidate_pool.save_pool(pool, job_dir)

        # === 6. 编排（storyboard 或 AI EDL）===
        s_cfg = config.get_style_config(yaml_cfg, config_in.style)
        cd_range = s_cfg.get("cut_duration_range")
        if cd_range and len(cd_range) == 2:
            cd_range = (float(cd_range[0]), float(cd_range[1]))
        else:
            cd_range = None

        board = None
        edl_cfg = yaml_cfg.get("edl", {})
        edl_enabled = (
            use_edl
            and edl_cfg.get("enabled", False)
            and config_in.provider in (Provider.GLM, Provider.DOUBAO)
        )
        if edl_enabled:
            logger.info("[6/7] AI EDL 规划（fallback storyboard）")
            try:
                edl_obj = edl_planner.plan_edl(
                    pool, config_in, provider,
                    target_duration=config_in.target_duration,
                    max_candidates=int(edl_cfg.get("max_candidates", 40)),
                    tolerance=float(edl_cfg.get("target_duration_tolerance", 0.2)),
                    fallback_models=list(edl_cfg.get("fallback_models", ["glm-4-plus"])),
                    primary_model=edl_cfg.get("primary_model"),
                    prompts_path=effective_prompts_path,
                    logger=logger,
                )
                edl_path = edl_planner.save_edl(edl_obj, job_dir)
                board = edl_planner.edl_to_storyboard(edl_obj)
                used_edl = True
                logger.info(
                    f"[6/7] EDL 规划成功: narrative={edl_obj.narrative[:40]!r}, "
                    f"{len(edl_obj.selected)} 段, 时长 {edl_obj.expected_duration_sec:.2f}s"
                )
            except Exception as e:
                if edl_cfg.get("fallback_to_storyboard", True):
                    logger.warning(f"[6/7] EDL 失败，fallback storyboard: {e}")
                    board = None
                else:
                    raise
        else:
            logger.info(
                f"[6/7] storyboard 编排 (use_edl={use_edl}, yaml.enabled={edl_cfg.get('enabled', False)})")

        if board is None:
            # 注入 creation_time（用于 timeline 序和 LLM 阶段聚类的输入顺序）
            creation_times: dict[str, str] = {}
            try:
                creation_times = timeline_dedup.read_src_creation_times(
                    Path(config_in.input_path), Path(config_in.ffmpeg_path), logger=logger,
                )
                if logger:
                    non_empty = sum(1 for v in creation_times.values() if v)
                    logger.info(f"[6/7] 读 creation_time: {non_empty}/{len(creation_times)} 个源有效")
            except Exception as e:
                if logger:
                    logger.warning(f"[6/7] 读 creation_time 失败（用 id 自然序兜底）: {e}")

            stages: Optional[list[dict]] = None
            # 加载 skill snippet（llm/default 模式下注入到 LLM prompt）
            skill_snippet = ""
            skill_name_resolved = ""
            try:
                from .skill_loader import load_skill, match_skill_for_scenes
                skill_cfg = (config_in.skill or "auto").strip().lower()
                resolved = None
                if skill_cfg and skill_cfg not in ("auto", "none"):
                    resolved = load_skill(skill_cfg)
                elif skill_cfg == "auto":
                    scenes_for_match = [
                        {"main_objects": a.main_objects, "action_type": a.action_type}
                        for a in analyzed
                    ]
                    resolved = match_skill_for_scenes(scenes_for_match)
                if resolved:
                    skill_snippet = resolved.full_prompt_block()
                    skill_name_resolved = resolved.name
                    if logger:
                        logger.info(f"[6/7] 加载 skill: {resolved.name}"
                                    f"（prompt block {len(skill_snippet)} 字）")
            except Exception as e:
                if logger:
                    logger.warning(f"[6/7] skill 加载失败（忽略）: {e}")

            if config_in.orchestration_mode in ("llm", "default"):
                if provider is None:
                    provider = vision_analyze.get_provider(
                        config_in.provider.value,
                        api_key=api_key,
                        model=model,
                        mode=mode,
                        auth_token=auth_token,
                        proxy_base_url=proxy_base_url,
                        logger=logger,
                    )

        # === 6/7 + 7/7 variant 循环（vision 复用，每个 variant 重新 LLM 编排 + render）===
        total_variants = max(1, config_in.variants)
        r_cfg = yaml_cfg.get("render", {})

        for v_idx in range(1, total_variants + 1):
            style_hint = _get_style_hint(v_idx) if total_variants > 1 else ""
            if logger:
                logger.info(f"[6-7/7] variant {v_idx}/{total_variants}"
                            f" (style_hint={'默认' if not style_hint else style_hint[:30] + '...'})")

            try:
                # ---- 6. LLM 阶段聚类（每 variant 重做，注入 style_hint）----
                stages = None
                if config_in.orchestration_mode in ("llm", "default"):
                    from .storyboard import _timeline_key, _source_id
                    sorted_for_llm = sorted(analyzed, key=lambda a: _timeline_key(a, creation_times))
                    scenes_for_llm = [
                        {**a.model_dump(), "source_id": _source_id(a)}
                        for a in sorted_for_llm
                    ]
                    try:
                        llm_model = model or "ep-20260712162006-kcfdm"
                        stages = timeline_dedup.cluster_by_timeline(
                            scenes_for_llm, provider, llm_model, logger=logger,
                            skill_snippet=skill_snippet,
                            style_hint=style_hint,
                        )
                        if logger:
                            logger.info(f"[6/7] v{v_idx} LLM 阶段聚类: {len(stages)} stages"
                                        f"（skill={skill_name_resolved or 'none'}）")
                    except Exception as e:
                        if logger:
                            logger.warning(f"[6/7] v{v_idx} LLM 聚类失败，退回 timeline: {e}")
                        stages = None

                # ---- storyboard.plan ----
                board = storyboard.plan(analyzed, config_in, target_duration=config_in.target_duration,
                                        cut_duration_range=cd_range,
                                        orchestration_mode=config_in.orchestration_mode,
                                        creation_times=creation_times,
                                        stages=stages,
                                        style_hint=style_hint,
                                        logger=logger)

                # ---- 落盘 storyboard ----
                if total_variants == 1:
                    sb_path = storyboard.save_storyboard(board, job_dir)
                else:
                    sb_path = job_dir / "work" / f"storyboard_v{v_idx}.json"
                    sb_path.write_text(
                        json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                if v_idx == 1:
                    board_path = sb_path  # result.storyboard 指向第一个

                progress.report(config_in.job_id, JobStatus.PLANNED, work_root=config_in.work_root)

                # ---- 7. 渲染 ----
                v_final = None
                if skip_render:
                    if logger:
                        logger.info(f"[7/7] v{v_idx} skip_render=True，跳过渲染")
                else:
                    if logger:
                        logger.info(f"[7/7] v{v_idx} FFmpeg 渲染")
                    mp4_name = "final.mp4" if total_variants == 1 else f"final_v{v_idx}.mp4"
                    v_final = render.render(
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
                        xfade_dur=r_cfg.get("xfade_dur", 0.0),
                        output_filename=mp4_name,
                        logger=logger,
                    )
                    if v_idx == 1:
                        final_video = v_final

                # ---- 7.5 LLM 剪辑思路叙述 ----
                v_narrative: Optional[str] = None
                if config_in.orchestration_mode in ("llm", "default") and not skip_render:
                    try:
                        from .narrative_writer import write_narrative
                        llm_model_n = model or "ep-20260712162006-kcfdm"
                        v_narrative = write_narrative(
                            board, analyzed, config_in.orchestration_mode,
                            provider, llm_model_n,
                            target=config_in.target_duration, logger=logger,
                            skill_snippet=skill_snippet,
                        )
                        board.narrative = v_narrative
                        # 重写该 variant 的 storyboard 让 narrative 落盘
                        sb_path.write_text(
                            json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
                            encoding="utf-8",
                        )
                        if v_idx == 1:
                            narrative_text = v_narrative
                    except Exception as e:
                        if logger:
                            logger.warning(f"[7.5] v{v_idx} narrative 失败（不影响主流程）: {e}")

                variant_results.append(VariantResult(
                    index=v_idx,
                    style_hint=style_hint,
                    storyboard=sb_path,
                    final_video=v_final,
                    narrative=v_narrative,
                ))
            except Exception as e:
                if logger:
                    logger.exception(f"variant {v_idx} 失败（不影响其他 variant）: {e}")
                variant_results.append(VariantResult(
                    index=v_idx, style_hint=style_hint, error=str(e),
                ))

        # 至少 1 个 variant 出片才算成功（skip_render 时只要有 storyboard 就算）
        successful = [v for v in variant_results if v.final_video or (skip_render and v.storyboard)]
        if not successful:
            raise RuntimeError(f"所有 {total_variants} 个 variant 都失败")

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
        candidate_pool=pool_path, edl=edl_path,
        narrative=narrative_text,
        variants=variant_results,
    )

    # 持久化 result
    (job_dir / "logs" / "result.json").write_text(
        json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(f"=== job 结束 status={status.value} duration={duration:.1f}s ===")
    return result
