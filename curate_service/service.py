"""手动剪辑业务逻辑（纯库，供 scripts/curate_cli.py 调用）

回调约定：
- on_log(level: str, msg: str) — 日志输出
- on_progress(done: int, todo: int, stage: str, msg: str) — 进度（done/todo 可为 0）

每个公共函数都是同步阻塞调用。subprocess 入口负责把 callback 接到 stdout JSON 协议上。
"""
from __future__ import annotations
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException

from .schemas import (
    CurateData, CurateResult, CurateResultItem, CurateSubmitPayload,
    RegeneratePayload,
    Scene, Stage,
)


# === 路径与外部依赖 ============================================

_SERVICE_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SERVICE_DIR.parent
SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
TOOLS_DIR = _PROJECT_ROOT / "tools"
FFMPEG_PATH = TOOLS_DIR / "ffmpeg.exe"

# jobs 根目录：env 优先（desktop 传 CURATE_JOBS_ROOT=APPDATA 路径），fallback 到项目根 jobs/
JOBS_ROOT = Path(os.environ.get("CURATE_JOBS_ROOT") or (_PROJECT_ROOT / "jobs"))

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# provider/model 由 desktop spawn 时通过 env 注入（参考 worker.ts）
CURATE_DEFAULT_PROVIDER = os.environ.get("WORKER_PROVIDER", "doubao-agent-plan")
DEFAULT_LLM_MODEL = os.environ.get("WORKER_MODEL", "doubao-seed-2.0-pro")

PREVIEW_CRF = 28
PREVIEW_MAX_DIM = 540
PREVIEW_WORKERS = min(8, (os.cpu_count() or 4))

LogCb = Optional[Callable[[str, str], None]]
ProgressCb = Optional[Callable[[int, int, str, str], None]]


def _default_log(level: str, msg: str) -> None:
    logging.getLogger("curate").log(
    getattr(logging, level.upper(), logging.INFO), msg)


# === 工具函数 ==================================================

def _job_dir(job_id: str) -> Path:
    p = JOBS_ROOT / job_id
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}")
    return p


def _load_input_dir(job_dir: Path) -> Optional[str]:
    """前端没传 input_dir 时，从 job_config.json 读 input_path 兜底。
    用途：保证 creation_time 注入成功，timeline_dedup 按真实拍摄时间排序。"""
    cfg = job_dir / "logs" / "job_config.json"
    if not cfg.exists():
        return None
    try:
        return json.loads(cfg.read_text(encoding="utf-8")).get("input_path")
    except Exception:
        return None


def _load_analyzed(job_dir: Path) -> list[dict]:
    f = job_dir / "work" / "analyzed.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"analyzed.json 不存在: {f}")
    analyzed = json.loads(f.read_text(encoding="utf-8"))
    for a in analyzed:
        src = a.get("src")
        if not src:
            continue
        if not Path(src).is_absolute():
            src = str((_PROJECT_ROOT / src).resolve())
            a["src"] = src
        # source_id 从 src 文件名取（id 字段可能带 triplet 后缀如 02-1_0_t1，rsplit 不准）
        a["source_id"] = Path(src).stem
    return analyzed


def _build_scenes_with_time(analyzed: list[dict], input_dir: Optional[str],
                             on_log: LogCb = None) -> list[dict]:
    src_to_time: dict[str, str] = {}
    if input_dir:
        try:
            from video_worker.timeline_dedup import read_creation_time  # type: ignore
            from video_worker.paths import resolve_ffmpeg
            ffmpeg = resolve_ffmpeg(FFMPEG_PATH)
            src_dir = Path(input_dir)
            if src_dir.exists():
                for src in sorted(src_dir.glob("*.MP4")):
                    try:
                        src_to_time[src.stem] = read_creation_time(ffmpeg, src)
                    except Exception:
                        src_to_time[src.stem] = ""
        except Exception as e:
            (on_log or _default_log)("warn", f"读 creation_time 失败: {e}")

    out = []
    for a in analyzed:
        sc = dict(a)
        # source_id 已在 _load_analyzed 里从 src 推导
        seg = a.get("source_id") or a["id"].rsplit("_", 1)[0]
        sc["source_id"] = seg
        sc["creation_time"] = src_to_time.get(seg, "")
        out.append(sc)
    return out


# === load_curate_data ==========================================

def load_curate_data(job_id: str, input_dir: Optional[str] = None,
                     on_log: LogCb = None) -> CurateData:
    """懒加载 stages + scenes。命中 curate_stages.json 秒回；否则跑 LLM dedup + 落盘。
    返回前不切预览（预览是独立调用 build_previews）。"""
    on_log = on_log or _default_log
    job_dir = _job_dir(job_id)
    cache_path = job_dir / "work" / "curate_stages.json"
    if not input_dir:
        input_dir = _load_input_dir(job_dir)
    analyzed = _load_analyzed(job_dir)

    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            on_log("info", f"命中缓存 {cache_path.name}")
            return _assemble_curate_data(job_id, input_dir, cached, analyzed, job_dir)
        except Exception as e:
            on_log("warn", f"缓存损坏，重建: {e}")

    on_log("info", "首次生成 stages（调用 LLM, 10-30s）...")
    scenes = _build_scenes_with_time(analyzed, input_dir, on_log)

    # 不过滤 score——上游 VLM 可能没出分（全 0），故事完整性优先让所有段都进 candidates
    candidates = list(scenes)
    candidates.sort(key=lambda s: s.get("creation_time") or "9999")

    from video_worker import vision_analyze
    from video_worker.timeline_dedup import cluster_by_timeline

    provider = vision_analyze.get_provider(
        CURATE_DEFAULT_PROVIDER, model=DEFAULT_LLM_MODEL, logger=logging.getLogger("curate"),
    )
    stages = cluster_by_timeline(
        candidates, provider, DEFAULT_LLM_MODEL,
        logger=logging.getLogger("curate"),
    )

    cached = {
        "stages": stages,
        "input_dir": input_dir,
        "created_at": str(__import__("datetime").datetime.now()),
    }
    cache_path.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
    on_log("info", f"stages 落盘（{len(stages)} stages）")

    return _assemble_curate_data(job_id, input_dir, cached, analyzed, job_dir)


def _load_auto_selected_ids(job_dir: Path) -> list[str]:
    """读 worker 自动成片用的 storyboard.json，提取 selected[].id。
    用于让 curate 页面默认勾选反映"worker 实际用了哪些段"。"""
    sb_path = job_dir / "work" / "storyboard.json"
    if not sb_path.exists():
        return []
    try:
        sb = json.loads(sb_path.read_text(encoding="utf-8"))
        return [it["id"] for it in sb.get("selected", []) if it.get("id")]
    except Exception:
        return []


def _assemble_curate_data(job_id: str, input_dir: Optional[str], cached: dict,
                          analyzed: list[dict], job_dir: Path) -> CurateData:
    scenes_by_id: dict[str, Scene] = {}
    analyzed_by_id = {a["id"]: a for a in analyzed}

    previews_dir = job_dir / "work" / "previews"
    for sid in analyzed_by_id:
        a = analyzed_by_id[sid]
        seg = a.get("source_id") or sid.rsplit("_", 1)[0]
        preview_path = previews_dir / f"{sid}.mp4"
        scenes_by_id[sid] = Scene(
            id=sid,
            source_id=seg,
            start=a.get("start", 0.0),
            end=a.get("end", 0.0),
            creation_time="",
            action_type=a.get("action_type", ""),
            main_objects=a.get("main_objects") or [],
            highlight_score=a.get("highlight_score", 5),
            visual_quality=a.get("visual_quality", 5),
            motion_score=a.get("motion_score", 5),
            preview_path=str(preview_path),
            preview_ready=preview_path.exists(),
        )

    stages_out = [
        Stage(
            id=f"stage_{st['stage']}",
            title=st.get("theme", f"stage_{st['stage']}"),
            scene_ids=st.get("members", []),
            representative=st.get("representative"),
            size=st.get("size", len(st.get("members", []))),
        )
        for st in cached.get("stages", [])
    ]

    all_ready = all(s.preview_ready for s in scenes_by_id.values()) if scenes_by_id else False
    auto_ids = [i for i in _load_auto_selected_ids(job_dir) if i in scenes_by_id]

    return CurateData(
        job_id=job_id,
        input_dir=input_dir or "",
        target_duration_default=60.0,
        stages=stages_out,
        scenes_by_id=scenes_by_id,
        previews_ready=all_ready,
        auto_selected_ids=auto_ids,
    )


# === build_previews ============================================

def build_previews(job_id: str, on_log: LogCb = None,
                   on_progress: ProgressCb = None) -> None:
    """幂等切预览 MP4。"""
    from video_worker.render import cut_clip
    from video_worker.paths import resolve_ffmpeg

    on_log = on_log or _default_log
    job_dir = _job_dir(job_id)
    analyzed = _load_analyzed(job_dir)
    previews_dir = job_dir / "work" / "previews"
    previews_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = resolve_ffmpeg(FFMPEG_PATH)

    clips_root = job_dir / "work" / "clips"
    todo_list = []
    for a in analyzed:
        out = previews_dir / f"{a['id']}.mp4"
        if not (out.exists() and out.stat().st_size > 3000):
            todo_list.append(a)

    if not todo_list:
        on_log("info", f"所有预览已就绪 ({len(analyzed)} 段)")
        if on_progress:
            on_progress(len(analyzed), len(analyzed), "previews", "已就绪")
        return

    on_log("info", f"切预览 MP4：{len(todo_list)}/{len(analyzed)} 段待处理（{PREVIEW_WORKERS} 路并发）")
    if on_progress:
        on_progress(0, len(todo_list), "previews", "开始切预览")

    # 并发跑 ffmpeg：cut_clip 是无状态 subprocess，线程安全
    done_state = {"n": 0}
    counter_lock = threading.Lock()
    grade = f"scale=-2:{PREVIEW_MAX_DIM}"
    todo_total = len(todo_list)

    def process_one(a: dict) -> bool:
        sid = a["id"]
        out = previews_dir / f"{sid}.mp4"
        # 直接用 src 字段，避免从 id 反推时 triplet 后缀（如 02-1_0_t1）切错
        src = Path(a.get("src") or "")
        if not src.exists():
            on_log("warn", f"源 clip 不存在: {src}")
            return False
        start = a.get("start", 0.0)
        end = a.get("end", 0.0)
        ok = cut_clip(
            src=src, us=start, ue=end, out=out,
            ffmpeg_path=ffmpeg, grade_filter=grade,
            crf=PREVIEW_CRF, stabilize=False,
            logger=logging.getLogger("curate"),
        )
        with counter_lock:
            done_state["n"] += 1
            n = done_state["n"]
            if n % 20 == 0 or n == todo_total:
                on_log("info", f"预览进度 {n}/{todo_total}")
            if on_progress:
                on_progress(n, todo_total, "previews", f"{n}/{todo_total}")
        return ok

    with ThreadPoolExecutor(max_workers=PREVIEW_WORKERS) as ex:
        results = list(ex.map(process_one, todo_list))

    ok_count = sum(1 for r in results if r)
    on_log("info", f"预览就绪: +{ok_count}/{todo_total}")
    if on_progress:
        on_progress(ok_count, todo_total, "previews", "完成")


# === run_curation =============================================

def run_curation(job_id: str, input_dir: Optional[str], payload: CurateSubmitPayload,
                 on_log: LogCb = None, on_progress: ProgressCb = None) -> CurateResult:
    """同步阻塞：LLM 决策 + 渲染，返回 CurateResult。"""
    on_log = on_log or _default_log
    job_dir = _job_dir(job_id)
    if not input_dir:
        input_dir = _load_input_dir(job_dir)
    analyzed = _load_analyzed(job_dir)
    scenes = _build_scenes_with_time(analyzed, input_dir, on_log)

    # flatten selections
    scene_ids: list[str] = []
    for sel in payload.selections:
        scene_ids.extend(sel.scene_ids)
    seen = set()
    scene_ids = [x for x in scene_ids if not (x in seen or seen.add(x))]
    if not scene_ids:
        raise HTTPException(status_code=400, detail="未勾选任何段")

    if on_progress:
        on_progress(0, 3, "llm", "LLM 决策中")
    on_log("info", f"LLM 决策中（{len(scene_ids)} 段勾选，target={payload.target_duration}s）")

    from tandao2_hybrid_test import curate_with_selection  # type: ignore
    from video_worker import vision_analyze

    provider = vision_analyze.get_provider(
        payload.provider, model=payload.llm_model,
        logger=logging.getLogger("curate"),
    )
    selections = curate_with_selection(
        scenes, scene_ids, payload.target_duration,
        provider, payload.llm_model,
        logger=logging.getLogger("curate"),
        brief=payload.brief,
    )
    if not selections:
        raise RuntimeError("LLM 没选出任何段")
    narrative = selections[0].get("narrative", "")

    if on_progress:
        on_progress(1, 3, "storyboard", "构造 storyboard")
    on_log("info", f"LLM 选出 {len(selections)} 段，构造 storyboard")

    from video_worker.validators import (
        JobConfig, Storyboard, StoryboardItem, Style, Provider,
    )
    from video_worker import config, render as render_mod
    from video_worker.paths import resolve_ffmpeg

    # 不按 creation_time 重排——保留 LLM 输出顺序（=用户拖拽 stage 后的顺序）。
    # 前端按 stageOrder 传 selections，curate_with_selection 把 pool_info 也按这个序排给 LLM，
    # LLM 被约束按输入顺序输出，整条链路保持用户的拖拽意图。

    ffmpeg = resolve_ffmpeg(FFMPEG_PATH)
    items: list[StoryboardItem] = []
    for i, sel in enumerate(selections, 1):
        s = sel["scene"]
        a_start = s["start"]
        a_end = s["end"]
        a_dur = a_end - a_start
        desired = min(sel["duration"], a_dur)
        use_start = a_start + (a_dur - desired) / 2
        use_end = use_start + desired
        items.append(StoryboardItem(
            order=i,
            id=sel["id"],
            cut_duration=round(use_end - use_start, 3),
            subtitle=None,
            use_start=round(use_start, 3),
            use_end=round(use_end, 3),
            reason=f"curated: {sel['reason']}",
        ))

    import time as _time
    suffix_ts = _time.strftime("%Y%m%d_%H%M%S")
    storyboard_path = job_dir / "work" / f"storyboard_curated_{suffix_ts}.json"

    board = Storyboard(
        narrative=narrative or f"curated by user ({len(items)}段)",
        target_duration_sec=int(payload.target_duration),
        expected_duration_sec=sum(it.cut_duration for it in items),
        selected=items,
    )
    storyboard_path.write_text(
        json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    if on_progress:
        on_progress(2, 3, "render", "渲染中")
    on_log("info", "渲染中")

    cfg = JobConfig(
        job_id=job_id,
        input_path=input_dir or "",
        platform="general",
        style=Style.NARRATIVE,
        target_duration=int(payload.target_duration),
        provider=Provider.DOUBAO,
        work_root=str(JOBS_ROOT),
        ffmpeg_path=str(ffmpeg),
        config_path=_PROJECT_ROOT / "configs" / "default.yaml",
        natural_language_request=f"curated-{payload.target_duration}s",
    )
    yaml_cfg = config.load_yaml(cfg.config_path)
    config.apply_platform_overrides(cfg, yaml_cfg)
    p_cfg = config.get_platform_config(yaml_cfg, cfg.platform)
    r_cfg = yaml_cfg.get("render", {})

    from video_worker.validators import AnalyzedScene
    analyzed_scenes = [AnalyzedScene(**a) for a in analyzed]

    final_video = render_mod.render(
        board, analyzed_scenes,
        cfg, job_dir,
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
        force_recut=True,
        output_filename=f"final_curated_{suffix_ts}.mp4",
        logger=logging.getLogger("curate"),
    )

    result = CurateResult(
        final_video=str(final_video),
        narrative=narrative,
        items=[
            CurateResultItem(
                order=it.order, id=it.id,
                cut_duration=it.cut_duration,
                use_start=it.use_start, use_end=it.use_end,
                reason=it.reason or "",
            ) for it in items
        ],
        total_duration=sum(it.cut_duration for it in items),
    )
    if on_progress:
        on_progress(3, 3, "done", "完成")
    on_log("info", f"渲染完成: {final_video}")
    return result


# === 预览文件路径 ==============================================

def _load_latest_storyboard_items(job_dir: Path) -> list[dict]:
    """读最新的 storyboard_*.json，提取 selected items。
    优先 curated → 普通 storyboard。"""
    work_dir = job_dir / "work"
    # 优先用 curate 后的 storyboard_curated_*.json（用户手动剪辑结果）
    curated = sorted(work_dir.glob("storyboard_curated_*.json"), reverse=True)
    if curated:
        try:
            sb = json.loads(curated[0].read_text(encoding="utf-8"))
            return [
                {"id": it["id"], "duration": it["cut_duration"], "reason": it.get("reason", "")}
                for it in sb.get("selected", [])
            ]
        except Exception:
            pass
    # fallback 1：默认 storyboard.json（worker 单视频成片）
    sb_path = work_dir / "storyboard.json"
    if sb_path.exists():
        try:
            sb = json.loads(sb_path.read_text(encoding="utf-8"))
            return [
                {"id": it["id"], "duration": it["cut_duration"], "reason": it.get("reason", "")}
                for it in sb.get("selected", [])
            ]
        except Exception:
            pass
    # fallback 2：多变体模式的 storyboard_v1.json（默认平衡 variant 作为再编辑基础）
    v1_path = work_dir / "storyboard_v1.json"
    if v1_path.exists():
        try:
            sb = json.loads(v1_path.read_text(encoding="utf-8"))
            return [
                {"id": it["id"], "duration": it["cut_duration"], "reason": it.get("reason", "")}
                for it in sb.get("selected", [])
            ]
        except Exception:
            pass
    return []


def _filter_by_user_instruction(
    analyzed: list,
    instruction: str,
    provider,
    llm_model: str,
    on_log: LogCb = None,
) -> tuple[list, set]:
    """LLM 读用户自然语言指令 + 全部段元数据，返回需要丢弃的 id 集合。

    用于再编辑场景：storyboard.plan 的选段是硬编码 SCORE_WEIGHTS，看不到用户自由文本。
    这里先让 LLM 把"去掉 X"翻译成具体的 discard_ids，从候选池直接删除。

    返回：(过滤后的 analyzed 列表, 被丢弃的 id 集合)
    LLM 失败时返回原列表不丢任何段（log warning）。
    """
    if not instruction.strip() or not analyzed:
        return analyzed, set()

    import json as _json
    from video_worker.providers.base import parse_json_response

    # 精简段元数据（避免 prompt 过长）
    seg_meta = []
    for a in analyzed:
        seg_meta.append({
            "id": a.id,
            "main_objects": list(a.main_objects or [])[:5],  # top 5
            "action_type": a.action_type or "",
            "story_role": a.story_role or "",
            "highlight_score": a.highlight_score,
            "shaky": bool(a.shaky),
            "bad_reason": a.bad_reason or "",
        })

    prompt = f"""用户要再编辑视频，要求：
{instruction.strip()}

下面是所有候选段的元数据（共 {len(seg_meta)} 段）。请判断哪些段需要**坚决丢弃**。

段元数据：
{_json.dumps(seg_meta, ensure_ascii=False, indent=2)}

**判断规则**：
1. 如果用户说"去掉 X / 不要 X / 删除 X"，所有 action_type 或 main_objects 与 X 相关的段都要 discard。
   - 例如"去掉清洁场景" → action_type 含 "clean" 或 main_objects 含清洁用品的段
   - 例如"去掉 walking" → action_type == "walking" 的段
   - 例如"去掉晃动" → shaky == true 或 bad_reason 含 shaky 的段
2. **宁可多丢不要少丢**——用户说"去掉"就是坚决不要，相关段全部丢弃。
3. 如果用户要求"压缩到 N 秒"，**不在这里处理**（保持原段数，让编排阶段处理时长）。
4. 如果用户要求"加快/放慢节奏"，**不在这里处理**（不丢段，只影响 cut_duration）。
5. 如果指令不涉及具体段过滤（例如"中段加慢镜头"），返回空 discard_ids。

**输出 JSON**：
{{
  "discard_ids": ["<scene_id>", ...],
  "reason": "<30 字内说明丢弃逻辑>"
}}
"""
    original_model = provider.model
    provider.model = llm_model
    try:
        if on_log:
            on_log("info", f"[filter] 调 {llm_model} 解析约束（{len(seg_meta)} 段）...")
        raw = provider.chat(prompt, max_tokens=2048)
        data = parse_json_response(raw)
        if not data or "discard_ids" not in data:
            if on_log:
                on_log("warn", f"[filter] LLM 返回无效，跳过过滤: {raw[:200]!r}")
            return analyzed, set()
    except Exception as e:
        if on_log:
            on_log("warn", f"[filter] LLM 调用失败，跳过过滤: {e}")
        return analyzed, set()
    finally:
        provider.model = original_model

    discard_list = data.get("discard_ids") or []
    valid_ids = {a.id for a in analyzed}
    discard_set = {sid for sid in discard_list if sid in valid_ids}

    reason = data.get("reason", "")
    if reason and on_log:
        on_log("info", f"[filter] LLM 解释：{reason}")

    filtered = [a for a in analyzed if a.id not in discard_set]
    return filtered, discard_set


def regenerate_with_instruction(job_id: str, input_dir: Optional[str],
                                 payload: RegeneratePayload,
                                 on_log: LogCb = None,
                                 on_progress: ProgressCb = None) -> CurateResult:
    """自然语言再编辑：按原任务 variants 数重跑全部 variant，注入用户指令作为约束。

    策略：
    - 读原 job_config.json，复用 variants/orchestration_mode/style/platform/provider
    - 每个 variant：base style_hint + 用户指令 → effective_hint
    - 走完整 pipeline：cluster_by_timeline → storyboard.plan → render
    - 输出覆盖 final_v{i}.mp4 + storyboard_v{i}.json（让前端 variants 网格自然刷新）
    """
    on_log = on_log or _default_log
    job_dir = _job_dir(job_id)
    if not input_dir:
        input_dir = _load_input_dir(job_dir)

    # 读原任务配置
    cfg_path = job_dir / "logs" / "job_config.json"
    if not cfg_path.exists():
        raise HTTPException(status_code=400, detail="找不到原任务配置 job_config.json")
    orig_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    total_variants = max(1, int(orig_cfg.get("variants") or 1))

    # 始终用原任务的 target_duration（用户要求"按原任务设定再编辑"）
    # payload.target_duration 仅作为兜底，正常不会用到
    target_duration = int(orig_cfg.get("target_duration") or payload.target_duration or 30)

    user_inst = (payload.instruction or "").strip()
    on_log("info", f"再编辑：{total_variants} 个 variant / target={target_duration}s / 指令={user_inst!r}")

    analyzed_raw = _load_analyzed(job_dir)

    from video_worker.validators import (
        JobConfig, Style, Platform, Provider, AnalyzedScene,
    )
    from video_worker import (
        config, storyboard as sb_mod, render as render_mod,
        timeline_dedup, vision_analyze,
    )
    from video_worker.paths import resolve_ffmpeg
    from video_worker.job import VARIANT_STYLE_HINTS

    ffmpeg = resolve_ffmpeg(FFMPEG_PATH)

    # provider 用前端传的（已根据用户配置动态挑选）
    provider = vision_analyze.get_provider(
        payload.provider, model=payload.llm_model,
        logger=logging.getLogger("curate"),
    )

    # 重建 JobConfig（复用原任务的关键字段）
    try:
        platform = Platform(orig_cfg.get("platform", "general"))
    except ValueError:
        platform = Platform.GENERAL
    try:
        style = Style(orig_cfg.get("style", "narrative"))
    except ValueError:
        style = Style.NARRATIVE
    try:
        prov_enum = Provider(orig_cfg.get("provider", payload.provider))
    except ValueError:
        prov_enum = Provider.DOUBAO

    cfg = JobConfig(
        job_id=job_id,
        input_path=input_dir or orig_cfg.get("input_path", "") or "",
        platform=platform,
        style=style,
        target_duration=target_duration,
        provider=prov_enum,
        work_root=str(JOBS_ROOT),
        ffmpeg_path=str(ffmpeg),
        config_path=_PROJECT_ROOT / "configs" / "default.yaml",
        orchestration_mode=orig_cfg.get("orchestration_mode", "default"),
        skill=orig_cfg.get("skill", "auto"),
        variants=total_variants,
        natural_language_request=f"regen: {user_inst[:80]}",
    )
    yaml_cfg = config.load_yaml(cfg.config_path)
    config.apply_platform_overrides(cfg, yaml_cfg)
    p_cfg = config.get_platform_config(yaml_cfg, cfg.platform)
    r_cfg = yaml_cfg.get("render", {})

    analyzed_scenes = [AnalyzedScene(**a) for a in analyzed_raw]

    # creation_times（timeline 序必要）
    input_path_obj = Path(cfg.input_path) if cfg.input_path else None
    creation_times: dict[str, str] = {}
    if input_path_obj and input_path_obj.exists():
        creation_times = timeline_dedup.read_src_creation_times(
            input_path_obj, ffmpeg, logger=logging.getLogger("curate"),
        )
    else:
        on_log("warn", f"input_path 不存在，跳过 creation_times: {cfg.input_path}")

    cd_range = (0.8, 1.5)
    # 总步数：用户约束过滤 1 步（如有指令）+ 每 variant 3 步（cluster + plan + render）
    total_steps = total_variants * 3 + (1 if user_inst else 0)
    cur_step = 0

    # === 用户约束预过滤（1 次额外 LLM 调用，所有 variant 共享）===
    # 解决"用户说去掉 X 但 storyboard.plan 不听"的问题：
    # storyboard.plan 的选段是硬编码 SCORE_WEIGHTS 逻辑，看不到用户的自由文本指令。
    # 这里先用 LLM 解析指令 → discard_ids，把这些段直接从候选池删除，
    # 后续 cluster/plan 只能在剩余段里选，100% 保证不再出现。
    if user_inst:
        cur_step += 1
        if on_progress:
            on_progress(cur_step, total_steps, "filter", "解析用户约束")
        filtered, discarded_ids = _filter_by_user_instruction(
            analyzed_scenes, user_inst, provider, payload.llm_model, on_log,
        )
        if discarded_ids:
            on_log("info", f"用户约束丢弃 {len(discarded_ids)}/{len(analyzed_scenes)} 段: "
                          f"{sorted(discarded_ids)[:10]}{'...' if len(discarded_ids) > 10 else ''}")
            if len(filtered) < 4:
                on_log("warn", f"过滤后只剩 {len(filtered)} 段（< 4），可能编不出完整视频；"
                              f"考虑放宽指令")
            analyzed_scenes = filtered

    results: list[dict] = []
    success_count = 0

    for v_idx in range(1, total_variants + 1):
        base_hint = VARIANT_STYLE_HINTS.get(v_idx, "") if total_variants > 1 else ""
        # 把用户指令拼到 hint 末尾，LLM 会自然遵守（"去掉晃动大的镜头"等约束）
        if user_inst:
            effective_hint = (base_hint + (" | " if base_hint else "")
                              + "用户再编辑要求：" + user_inst)
        else:
            effective_hint = base_hint
        hint_label = effective_hint[:50] + ("..." if len(effective_hint) > 50 else "")
        on_log("info", f"=== variant {v_idx}/{total_variants} (hint={hint_label}) ===")

        try:
            # 1. LLM 阶段聚类
            stages = None
            if cfg.orchestration_mode in ("llm", "default"):
                from video_worker.storyboard import _timeline_key, _source_id
                sorted_for_llm = sorted(
                    analyzed_scenes,
                    key=lambda a: _timeline_key(a, creation_times),
                )
                scenes_for_llm = [
                    {**a.model_dump(), "source_id": _source_id(a)}
                    for a in sorted_for_llm
                ]
                cur_step += 1
                if on_progress:
                    on_progress(cur_step, total_steps, "cluster",
                                f"v{v_idx} LLM 聚类中")
                stages = timeline_dedup.cluster_by_timeline(
                    scenes_for_llm, provider, payload.llm_model,
                    logger=logging.getLogger("curate"),
                    style_hint=effective_hint,
                )
                on_log("info", f"  v{v_idx} cluster: {len(stages)} stages")
            else:
                cur_step += 1
                if on_progress:
                    on_progress(cur_step, total_steps, "cluster", f"v{v_idx} 跳过")

            # 2. storyboard.plan
            cur_step += 1
            if on_progress:
                on_progress(cur_step, total_steps, "plan",
                            f"v{v_idx} 编排 storyboard")
            board = sb_mod.plan(
                analyzed_scenes, cfg,
                target_duration=target_duration,
                cut_duration_range=cd_range,
                orchestration_mode=cfg.orchestration_mode,
                creation_times=creation_times,
                stages=stages,
                style_hint=effective_hint,
                logger=logging.getLogger("curate"),
            )
            on_log("info", f"  v{v_idx} plan: {len(board.selected)} 段 "
                           f"/ {board.expected_duration_sec:.1f}s")

            # 落盘 storyboard_v{i}.json（覆盖原文件）
            sb_name = "storyboard.json" if total_variants == 1 else f"storyboard_v{v_idx}.json"
            sb_path = job_dir / "work" / sb_name
            sb_path.write_text(
                json.dumps(board.model_dump(), ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

            # 3. render（覆盖原 final_v{i}.mp4）
            cur_step += 1
            if on_progress:
                on_progress(cur_step, total_steps, "render", f"v{v_idx} 渲染中")
            mp4_name = "final.mp4" if total_variants == 1 else f"final_v{v_idx}.mp4"
            v_final = render_mod.render(
                board, analyzed_scenes, cfg, job_dir,
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
                logger=logging.getLogger("curate"),
            )
            on_log("info", f"  v{v_idx} 完成: {v_final}")
            results.append({
                "idx": v_idx, "hint": base_hint,
                "path": str(v_final),
                "narrative": board.narrative,
                "n_segments": len(board.selected),
                "duration": board.expected_duration_sec,
            })
            success_count += 1
        except Exception as e:
            on_log("error", f"  v{v_idx} 失败: {e}")
            results.append({"idx": v_idx, "hint": base_hint, "error": str(e)})
            # 该 variant 失败也算 3 步消耗，保持进度条线性（filter 步要算进去）
            cur_step = (1 if user_inst else 0) + v_idx * 3

    if success_count == 0:
        raise RuntimeError(f"所有 {total_variants} 个 variant 都失败")

    # 写再编辑历史（便于排查；前端主要靠 workerApi.getJobDetail 刷新 variants 网格）
    import time as _time
    suffix_ts = _time.strftime("%Y%m%d_%H%M%S")
    regen_log_path = job_dir / "logs" / f"regen_history_{suffix_ts}.json"
    regen_log_path.write_text(
        json.dumps({
            "ts": suffix_ts,
            "instruction": user_inst,
            "target_duration": target_duration,
            "total_variants": total_variants,
            "success_count": success_count,
            "variants": results,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if on_progress:
        on_progress(total_steps, total_steps, "done",
                    f"完成（{success_count}/{total_variants}）")

    # 返回第一个成功的 variant 作为兜底 final_video；多变体展示靠前端刷新
    first_ok = next((r for r in results if "path" in r), None)
    summary = (f"再编辑「{user_inst}」完成：{success_count}/{total_variants} 个 variant "
               f"已更新（target={target_duration}s）")
    return CurateResult(
        final_video=first_ok["path"] if first_ok else None,
        narrative=summary,
        items=[],  # 多变体模式不返回单段 items
        total_duration=float(target_duration),
    )


def get_preview_path(job_id: str, scene_id: str) -> Path:
    job_dir = _job_dir(job_id)
    analyzed = _load_analyzed(job_dir)
    valid_ids = {a["id"] for a in analyzed}
    if scene_id not in valid_ids:
        raise HTTPException(status_code=404, detail=f"非法 scene_id: {scene_id}")
    if "/" in scene_id or "\\" in scene_id or ".." in scene_id:
        raise HTTPException(status_code=400, detail="scene_id 含非法字符")
    return job_dir / "work" / "previews" / f"{scene_id}.mp4"
