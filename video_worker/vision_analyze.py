"""
AI 视觉分析：调用 provider 适配器分析每个场景
- 默认 provider: qwen-vl（阿里）
- 也支持 doubao（字节）/ zai（MCP）/ mock（测试）
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from .validators import Scene, AnalyzedScene
from .providers.base import parse_json_response, validate_schema
from .paths import bundle_root


PROMPTS_DEFAULT_PATH = bundle_root() / "configs" / "prompts.yaml"


def load_prompts(path: Path = PROMPTS_DEFAULT_PATH) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def get_template(prompts_cfg: dict, task: str, vertical: str = "default") -> str:
    """从 prompts 配置取 prompt 模板"""
    templates = prompts_cfg.get("templates", {})
    task_cfg = templates.get(task, {})
    # 先按 vertical 找，找不到 fallback default
    tpl = task_cfg.get(vertical) or task_cfg.get("default", "")
    if not tpl:
        raise ValueError(f"prompt 模板不存在: task={task} vertical={vertical}")
    return tpl


def render_template(template: str, prompts_cfg: dict, vertical: str = "default") -> str:
    """填充 {vertical_prompt} 占位符"""
    verticals = prompts_cfg.get("verticals", {})
    vertical_prompt = verticals.get(vertical, verticals.get("default", ""))
    return template.replace("{vertical_prompt}", vertical_prompt)


def get_triplet_prompt(vertical: str = "default",
                       prompts_path: Path = PROMPTS_DEFAULT_PATH) -> str:
    """便捷方法：拿三联图检测 prompt"""
    cfg = load_prompts(prompts_path)
    tpl = get_template(cfg, "triplet_detect", vertical)
    return render_template(tpl, cfg, vertical)


def detect_shaky(scene: Scene,
                 threshold: float = 5.0,
                 num_frames: int = 8,
                 logger: Optional[logging.Logger] = None) -> bool:
    """
    用 OpenCV 光流检测场景是否抖动。
    抽 num_frames 帧算相邻帧 Farneback 光流，平均位移 > threshold 视为抖动。
    """
    import cv2
    import subprocess
    import tempfile
    from .paths import resolve_ffmpeg

    duration = scene.end - scene.start
    if duration <= 0.5:
        return False

    ff = str(resolve_ffmpeg(None))
    frames = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(num_frames):
            t = scene.start + duration * i / max(num_frames - 1, 1)
            frame_path = Path(tmpdir) / f"f{i:02d}.jpg"
            cmd = [ff, "-y", "-ss", f"{t:.3f}",
                   "-i", str(scene.src), "-vframes", "1",
                   str(frame_path)]
            try:
                subprocess.run(cmd, capture_output=True, timeout=10)
            except subprocess.TimeoutExpired:
                continue
            if frame_path.exists():
                img = cv2.imread(str(frame_path))
                if img is not None:
                    # 降采样加速光流（720 宽足够）
                    h, w = img.shape[:2]
                    if w > 720:
                        scale = 720 / w
                        img = cv2.resize(img, (720, int(h * scale)))
                    frames.append(img)

    if len(frames) < 4:
        return False

    displacements = []
    prev_gray = cv2.cvtColor(frames[0], cv2.COLOR_BGR2GRAY)
    for frame in frames[1:]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        flow = cv2.calcOpticalFlowFarneback(
            prev_gray, gray, None,
            0.5, 3, 15, 3, 5, 1.2, 0
        )
        mag = cv2.magnitude(flow[..., 0], flow[..., 1])
        displacements.append(float(mag.mean()))
        prev_gray = gray

    mean_disp = sum(displacements) / len(displacements) if displacements else 0.0
    is_shaky = mean_disp > threshold
    if logger:
        logger.info(f"[stab] {scene.id}: disp={mean_disp:.2f}px threshold={threshold} shaky={is_shaky}")
    return is_shaky


def analyze_scene(scene: Scene, frames: list[Path],
                  provider, prompt: Optional[str] = None,
                  logger: Optional[logging.Logger] = None,
                  prompts_path: Path = PROMPTS_DEFAULT_PATH) -> AnalyzedScene:
    """单场景分析。

    frames: 该场景的 N 帧 Path 列表（按时间顺序）。N>=2 时走多图模式；
            N==1 时退回单图（兼容）。空列表直接报错。
    """
    if not frames:
        raise ValueError(f"{scene.id} frames 为空，无法分析")
    if prompt is None:
        prompt = get_triplet_prompt(prompts_path=prompts_path)
    if len(frames) == 1:
        raw = provider.analyze_image(str(frames[0]), prompt)
    else:
        raw = provider.analyze_images([str(p) for p in frames], prompt)
    data = parse_json_response(raw) or {}
    if logger:
        logger.debug(f"[analyze] {scene.id}: {data}")

    # schema 校验 + 默认值兜底
    if not validate_schema(data, ["best_frame", "cut_duration"]):
        if logger:
            logger.warning(f"[analyze] {scene.id} schema 不全: {data}")

    # === 强校验 best_frame：必须是 left/mid/right，否则 warn + 兜底 mid ===
    VALID_BEST_FRAMES = {"left", "mid", "right"}
    raw_best_frame = str(data.get("best_frame", "mid")).strip().lower()
    if raw_best_frame not in VALID_BEST_FRAMES:
        if raw_best_frame and raw_best_frame != "none":
            if logger:
                logger.warning(
                    f"[analyze] {scene.id} best_frame 非法值 {raw_best_frame!r}，兜底为 mid"
                )
        raw_best_frame = "mid"

    # === cut_duration clamp 到 [0.3, 3.0]，超范围 warn ===
    CUT_DUR_MIN, CUT_DUR_MAX = 0.3, 3.0
    try:
        cut_dur = float(data.get("cut_duration", 1.0))
    except (TypeError, ValueError):
        cut_dur = 1.0
        if logger:
            logger.warning(
                f"[analyze] {scene.id} cut_duration 非数值 {data.get('cut_duration')!r}，兜底 1.0"
            )
    if cut_dur < CUT_DUR_MIN:
        if logger:
            logger.warning(
                f"[analyze] {scene.id} cut_duration={cut_dur:.2f} < {CUT_DUR_MIN}，clamp 到 {CUT_DUR_MIN}"
            )
        cut_dur = CUT_DUR_MIN
    elif cut_dur > CUT_DUR_MAX:
        if logger:
            logger.warning(
                f"[analyze] {scene.id} cut_duration={cut_dur:.2f} > {CUT_DUR_MAX}，clamp 到 {CUT_DUR_MAX}"
            )
        cut_dur = CUT_DUR_MAX
    # 上限再守一道：不能超过场景自身时长
    scene_dur = scene.end - scene.start
    if scene_dur > 0 and cut_dur > scene_dur:
        cut_dur = max(CUT_DUR_MIN, scene_dur)

    # main_objects：GLM 应返回 list；兼容旧版返回字符串
    raw_objects = data.get("main_objects")
    if isinstance(raw_objects, list):
        main_objects = [str(o).strip() for o in raw_objects if str(o).strip()]
    elif isinstance(raw_objects, str) and raw_objects.strip():
        # 旧版单字符串，按逗号/顿号切
        import re
        main_objects = [s.strip() for s in re.split(r"[,，、]", raw_objects) if s.strip()]
    else:
        main_objects = []
    # 兜底：旧数据可能只有 main_object 字段
    if not main_objects:
        legacy = data.get("main_object")
        if isinstance(legacy, str) and legacy.strip():
            main_objects = [legacy.strip()]

    # needs_stabilization：GLM 判断该不该稳（静物=true，运镜=false）
    needs_stab = bool(data.get("needs_stabilization", False))
    # 只在该稳定的场景跑光流检测（运镜直接跳过，省时间）
    shaky = False
    if needs_stab:
        try:
            shaky = detect_shaky(scene, threshold=5.0, num_frames=8, logger=logger)
        except Exception as e:
            if logger:
                logger.warning(f"[stab] {scene.id} 光流检测失败: {e}")

    # === 镜头评分字段解析（P3）===
    def _parse_score(field: str) -> int:
        """解析 1-10 评分，clamp + 默认 5"""
        raw = data.get(field, 5)
        try:
            v = int(round(float(raw)))
        except (TypeError, ValueError):
            if logger:
                logger.warning(f"[analyze] {scene.id} {field} 非数值 {raw!r}，兜底 5")
            return 5
        if v < 1:
            if logger:
                logger.warning(f"[analyze] {scene.id} {field}={v} < 1，clamp 到 1")
            return 1
        if v > 10:
            if logger:
                logger.warning(f"[analyze] {scene.id} {field}={v} > 10，clamp 到 10")
            return 10
        return v

    visual_quality = _parse_score("visual_quality")
    motion_score = _parse_score("motion_score")
    highlight_score = _parse_score("highlight_score")

    # story_role 白名单校验
    VALID_ROLES = {"opening", "process", "climax", "ending", "broll"}
    raw_role = str(data.get("story_role", "process")).strip().lower()
    if raw_role not in VALID_ROLES:
        if raw_role and raw_role != "process":
            if logger:
                logger.warning(
                    f"[analyze] {scene.id} story_role 非法值 {raw_role!r}，兜底 process"
                )
        raw_role = "process"

    # bad_reason：字符串，默认空
    bad_reason = str(data.get("bad_reason", "") or "").strip()

    return AnalyzedScene(
        id=scene.id,
        src=scene.src,
        start=scene.start,
        end=scene.end,
        dur=scene.dur,
        best_frame=raw_best_frame,
        cut_duration=cut_dur,
        best_moment=data.get("best_moment", ""),
        main_objects=main_objects,
        main_object=main_objects[0] if main_objects else "",
        action_type=data.get("action_type", "unknown"),
        needs_stabilization=needs_stab,
        shaky=shaky,
        visual_quality=visual_quality,
        motion_score=motion_score,
        highlight_score=highlight_score,
        story_role=raw_role,
        bad_reason=bad_reason,
    )


def analyze(scenes: list[Scene], frames_map: dict[str, list[Path]],
            provider, job_dir: Path,
            vertical: str = "default",
            prompt: Optional[str] = None,
            logger: Optional[logging.Logger] = None,
            max_workers: int = 5,
            max_retries: int = 3,
            prompts_path: Path = PROMPTS_DEFAULT_PATH) -> list[AnalyzedScene]:
    """
    批量分析（并发），持久化 analyzed.json。
    - frames_map: {scene_id: [frame_path, ...]}（多帧模式）或 {scene_id: [triplet_path]}（兼容旧版三联图模式）
    - resume：读已有 analyzed.json 跳过已分析场景
    - 并发：ThreadPoolExecutor(max_workers)，同一 API key 并行调用
    - 进度：每场景开始打 [analyze] i/total sc=xxx
    - 重试：429/网络抖动重试 max_retries 次（1/2/4s 退避）
    - 落盘：每个成功结果立即写（线程安全，按 scene id 排序）
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading
    import time

    if prompt is None:
        prompt = get_triplet_prompt(vertical, prompts_path=prompts_path)
    if logger:
        logger.info(f"[analyze] prompt {len(prompt)} chars, vertical={vertical}, max_workers={max_workers}")

    # resume：先读已有结果
    out_path = job_dir / "work" / "analyzed.json"
    results: dict[str, AnalyzedScene] = {}
    if out_path.exists():
        try:
            for raw in json.loads(out_path.read_text(encoding="utf-8")):
                a = AnalyzedScene(**raw)
                results[a.id] = a
            if logger:
                logger.info(f"[analyze] 命中缓存 {len(results)} 条")
        except Exception as e:
            if logger:
                logger.warning(f"[analyze] 读 analyzed.json 失败，重新开始: {e}")

    # 分离：需分析的 vs 缺帧的
    to_analyze: list[Scene] = []
    for sc in scenes:
        if sc.id in results:
            continue
        if sc.id in frames_map and frames_map[sc.id]:
            to_analyze.append(sc)
        else:
            if logger:
                logger.warning(f"[analyze] 缺帧数据 {sc.id}")

    total = len(to_analyze)
    if total == 0:
        if logger:
            logger.info(f"[analyze] 全部命中缓存，无需调 API")
        return [results[sc.id] for sc in scenes if sc.id in results]

    if logger:
        logger.info(f"[analyze] 并发分析 {total} 个场景（max_workers={max_workers}）")

    lock = threading.Lock()

    def analyze_one(idx: int, sc: Scene) -> None:
        fr = frames_map[sc.id]
        if logger:
            logger.info(f"[analyze] {idx}/{total} sc={sc.id} frames={len(fr)}")
        for attempt in range(max_retries):
            try:
                ana = analyze_scene(sc, fr, provider, prompt, logger, prompts_path=prompts_path)
                with lock:
                    results[sc.id] = ana
                    # 立即落盘（按 id 排序保证顺序稳定）
                    sorted_list = [results[sid] for sid in sorted(results.keys())]
                    out_path.write_text(
                        json.dumps([a.model_dump() for a in sorted_list],
                                   ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                return
            except Exception as e:
                if attempt < max_retries - 1:
                    backoff = 2 ** attempt  # 1, 2 秒
                    if logger:
                        logger.warning(f"[analyze] {sc.id} 第 {attempt+1}/{max_retries} 次失败: {e}，{backoff}s 后重试")
                    time.sleep(backoff)
                else:
                    if logger:
                        logger.error(f"[analyze] {sc.id} 重试 {max_retries} 次仍失败: {e}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(analyze_one, i, sc): sc
                   for i, sc in enumerate(to_analyze, 1)}
        for f in as_completed(futures):
            f.result()  # 触发内部未捕获异常（analyze_one 内已 try 兜底）

    success = sum(1 for sc in to_analyze if sc.id in results)
    if logger:
        logger.info(f"[analyze] 完成：新调用成功 {success}/{total}，总 {len(results)}/{len(scenes)}")

    # 按原始 scenes 顺序返回（拍摄时序）
    return [results[sc.id] for sc in scenes if sc.id in results]


def get_provider(provider_name: str, api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 mcp_caller=None,
                 mode: str = "direct",
                 auth_token: Optional[str] = None,
                 proxy_base_url: Optional[str] = None,
                 logger=None):
    """工厂方法：按 name 拿 provider 实例"""
    name = provider_name.lower()

    if name == "zai":
        from .providers.zai_provider import ZaiProvider
        return ZaiProvider(mcp_caller=mcp_caller, logger=logger)
    elif name == "qwen-vl":
        from .providers.qwen_vl import QwenVLProvider
        kwargs = {"api_key": api_key, "mode": mode}
        if model:
            kwargs["model"] = model
        if mode == "proxy":
            kwargs["auth_token"] = auth_token
            kwargs["proxy_base_url"] = proxy_base_url
        if logger:
            kwargs["logger"] = logger
        return QwenVLProvider(**kwargs)
    elif name in ("doubao", "doubao-agent-plan"):
        from .providers.doubao import DoubaoProvider
        kwargs = {"api_key": api_key, "mode": mode}
        if model:
            kwargs["model"] = model
        if name == "doubao-agent-plan" and mode != "proxy":
            # Agent Plan 订阅套餐专用 base URL（OpenAI 兼容）
            kwargs["base_url"] = "https://ark.cn-beijing.volces.com/api/plan/v3"
        if mode == "proxy":
            kwargs["auth_token"] = auth_token
            kwargs["proxy_base_url"] = proxy_base_url
        if logger:
            kwargs["logger"] = logger
        return DoubaoProvider(**kwargs)
    elif name == "glm":
        from .providers.glm import GLMProvider
        kwargs = {"api_key": api_key, "mode": mode}
        if model:
            kwargs["model"] = model
        if mode == "proxy":
            kwargs["auth_token"] = auth_token
            kwargs["proxy_base_url"] = proxy_base_url
        if logger:
            kwargs["logger"] = logger
        return GLMProvider(**kwargs)
    elif name == "mock":
        from .providers.zai_provider import MockProvider
        return MockProvider()
    else:
        raise ValueError(f"未知 provider: {provider_name}")
