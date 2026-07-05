"""
pydantic schema：JobConfig / JobResult / 中间数据结构
"""
from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Any, Optional
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
    main_object: str
    action_type: str


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
