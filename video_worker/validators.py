"""
pydantic schema：JobConfig / JobResult / 中间数据结构
"""
from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class JobStatus(str, Enum):
    CREATED = "created"
    PREPROCESSED = "preprocessed"
    TRIPLETS_READY = "triplets_ready"
    ANALYZED = "analyzed"
    PLANNED = "planned"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Platform(str, Enum):
    DOUYIN = "douyin"
    XHS = "xhs"
    VIDEOHAO = "videohao"
    GENERAL = "general"


class Style(str, Enum):
    FAST_CUT = "fast_cut"
    AMBIANCE = "ambiance"
    NARRATIVE = "narrative"


class Provider(str, Enum):
    ZAI = "zai"
    QWEN_VL = "qwen-vl"
    DOUBAO = "doubao"
    DOUBAO_AGENT_PLAN = "doubao-agent-plan"
    GLM = "glm"


# Phase 15：首次生成的编排模式（替代 Style 的 story-order 语义）
OrchestrationMode = Literal["timeline", "llm", "default"]


class ErrorInfo(BaseModel):
    stage: str
    code: str
    message: str
    ffmpeg_stderr: Optional[str] = None


class CostBreakdown(BaseModel):
    vision_calls: int = 0
    estimated_cost_cny: float = 0.0
    duration_sec: float = 0.0


class JobConfig(BaseModel):
    job_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_\-]+$")
    input_path: Path
    output_path: Optional[Path] = None
    platform: Platform = Platform.GENERAL
    style: Style = Style.FAST_CUT
    target_duration: int = Field(default=30, ge=5, le=300)
    bgm_path: Optional[Path] = None
    natural_language_request: Optional[str] = None
    provider: Provider = Provider.ZAI
    work_root: Path = Path("jobs")
    ffmpeg_path: Path = Path("tools/ffmpeg.exe")
    config_path: Optional[Path] = None
    orchestration_mode: OrchestrationMode = "timeline"
    # Phase 16：skill 名称（auto=自动匹配，none=不使用，其他为 configs/skills/<name>/）
    skill: str = "auto"
    # Phase 17：一次任务生成 N 个变体（vision 复用，循环 LLM+render）
    variants: int = Field(default=1, ge=1, le=10)

    @field_validator("input_path")
    @classmethod
    def validate_input_exists(cls, v: Path) -> Path:
        if not v.exists():
            raise ValueError(f"input_path 不存在: {v}")
        return v


class Scene(BaseModel):
    """PySceneDetect 切出的场景"""
    id: str
    src: Path
    seg: str
    sc_idx: int
    start: float
    end: float
    dur: float


class AnalyzedScene(BaseModel):
    """AI 视觉分析结果"""
    id: str
    src: Path
    start: float
    end: float
    dur: float
    best_frame: str  # left|mid|right
    cut_duration: float
    best_moment: str
    main_objects: list[str] = Field(default_factory=list)
    action_type: str
    # 兼容旧数据：单 main_object 字段（取 main_objects[0]）
    main_object: str = ""
    # 视频稳定：GLM 判断该不该稳（静物=true，运镜=false）
    needs_stabilization: bool = False
    # 视频稳定：光流检测有没有抖动（位移 > 阈值=true）
    shaky: bool = False
    # === 镜头评分（P3 镜头评分系统）===
    # 1-10 整数评分，5 = 中位（兼容老数据/未评估场景的默认值）
    visual_quality: int = 5      # 画质：清晰度、曝光、构图
    motion_score: int = 5        # 动态感：人物动作 / 镜头运动强度
    highlight_score: int = 5     # 高光程度：情绪 / 美学 / 稀缺性
    story_role: str = "process"  # opening|process|climax|ending|broll
    bad_reason: str = ""         # 非空 = 有质量问题（失焦/过曝/严重抖动等），选段时降权


class StoryboardItem(BaseModel):
    """编排后单个瞬时"""
    order: int
    id: str
    cut_duration: float
    subtitle: Optional[str] = None
    use_start: Optional[float] = None
    use_end: Optional[float] = None
    reason: Optional[str] = None


class Storyboard(BaseModel):
    narrative: str
    target_duration_sec: int
    expected_duration_sec: float
    selected: list[StoryboardItem]


# === Phase 14：候选池 + EDL ===

CandidateStatus = Literal["keep", "maybe", "discard"]


class CandidateClip(BaseModel):
    """候选池中的单个片段（包装 AnalyzedScene + 分流结果）"""
    id: str                       # 对应 AnalyzedScene.id
    status: CandidateStatus
    score: float                  # compute_score(analyzed) 快照
    reason: str                   # 30 字内分流理由
    analyzed: AnalyzedScene       # 内嵌，避免后续重复查找


class CandidatePool(BaseModel):
    job_id: str
    created_at: str
    keep: list[CandidateClip]
    maybe: list[CandidateClip]
    discard: list[CandidateClip]
    rule_summary: dict = Field(default_factory=dict)  # 阈值快照


class EDLItem(BaseModel):
    """AI 生成的 EDL 单段"""
    order: int
    id: str                       # 必须在 keep/maybe 中
    use_start: float
    use_end: float
    cut_duration: float
    story_role_assigned: str      # opening/climax/process/ending/hook/broll
    subtitle: Optional[str] = None
    reason: str = ""              # AI 入选理由


class EDL(BaseModel):
    job_id: str
    narrative: str                # AI 总结的一句话故事
    target_duration_sec: int
    expected_duration_sec: float
    selected: list[EDLItem]
    model: str = ""
    prompt_hash: str = ""


class VariantResult(BaseModel):
    """单个变体的渲染结果（一次任务可生成多个）"""
    index: int                        # 1-based 序号
    style_hint: str = ""              # 注入 LLM 的风格偏移
    storyboard: Optional[Path] = None
    final_video: Optional[Path] = None
    narrative: Optional[str] = None
    error: Optional[str] = None       # 该 variant 失败时的错误信息


class JobResult(BaseModel):
    job_id: str
    status: JobStatus
    final_video: Optional[Path] = None
    storyboard: Optional[Path] = None
    log: Optional[Path] = None
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
    error: Optional[ErrorInfo] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    # Phase 14：新中间产物
    candidate_pool: Optional[Path] = None
    edl: Optional[Path] = None
    # LLM 剪辑思路说明（llm/default 模式才有，timeline 为空）
    narrative: Optional[str] = None
    # Phase 17：多变体结果（variants=1 时长度为 1，等价于单视频）
    variants: list[VariantResult] = Field(default_factory=list)
