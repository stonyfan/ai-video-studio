"""
video_worker: AI 视频智能剪辑标准化 worker
唯一入口：process_job(JobConfig) -> JobResult
"""
from .validators import JobConfig, JobResult, JobStatus, ErrorInfo, CostBreakdown
from .job import process_job

__version__ = "0.1.0"
__all__ = ["process_job", "JobConfig", "JobResult", "JobStatus", "ErrorInfo", "CostBreakdown"]
