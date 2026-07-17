"""curate schemas — 手动剪辑 UI 的请求/响应模型"""
from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


class Scene(BaseModel):
    """单个候选片段的展示信息"""
    id: str
    source_id: str
    start: float
    end: float
    creation_time: str = ""
    action_type: str = ""
    main_objects: list[str] = Field(default_factory=list)
    highlight_score: int = 5
    visual_quality: int = 5
    motion_score: int = 5
    preview_path: str = ""
    preview_ready: bool = False


class Stage(BaseModel):
    """故事阶段，含若干 scene 成员"""
    id: str
    title: str
    scene_ids: list[str] = Field(default_factory=list)
    representative: Optional[str] = None
    size: int = 0


class CurateData(BaseModel):
    """GET /data 返回：所有 stage + 所有 scene 字典"""
    job_id: str
    input_dir: str
    target_duration_default: float = 60.0
    stages: list[Stage] = Field(default_factory=list)
    scenes_by_id: dict[str, Scene] = Field(default_factory=dict)
    previews_ready: bool = False
    auto_selected_ids: list[str] = Field(default_factory=list)


class Selection(BaseModel):
    """用户提交时单 stage 的勾选"""
    stage_id: str
    scene_ids: list[str] = Field(default_factory=list)


class CurateSubmitPayload(BaseModel):
    """POST /submit 请求体"""
    selections: list[Selection] = Field(default_factory=list)
    target_duration: float = 60.0
    brief: str = ""
    provider: str = "doubao"
    llm_model: str = "ep-20260712162006-kcfdm"


class RegeneratePayload(BaseModel):
    """自然语言再编辑请求体"""
    instruction: str
    target_duration: float = 60.0
    provider: str = "doubao"
    llm_model: str = "ep-20260712162006-kcfdm"


class CurateResultItem(BaseModel):
    """最终成片里的一段"""
    order: int
    id: str
    cut_duration: float
    use_start: float
    use_end: float
    reason: str = ""


class CurateResult(BaseModel):
    """渲染完成的成片信息"""
    final_video: str
    narrative: str = ""
    items: list[CurateResultItem] = Field(default_factory=list)
    total_duration: float = 0.0


class CurateTask(BaseModel):
    """异步任务状态"""
    task_id: str
    job_id: str
    status: Literal["pending", "running", "done", "error"] = "pending"
    progress: str = ""
    result: Optional[CurateResult] = None
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
