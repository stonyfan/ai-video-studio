"""
Provider 抽象基类 + 重试 + JSON 强制 + 成本统计
所有 provider 实现统一接口：analyze_image(image_path, prompt) -> str
"""
from __future__ import annotations
import base64
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@dataclass
class CallRecord:
    """单次 API 调用记录"""
    provider: str
    image_path: str
    prompt_chars: int
    success: bool
    duration_sec: float
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_cny: float = 0.0
    error: Optional[str] = None


@dataclass
class ProviderStats:
    """provider 调用累计统计"""
    calls: list[CallRecord] = field(default_factory=list)

    def add(self, record: CallRecord) -> None:
        self.calls.append(record)

    @property
    def total_calls(self) -> int:
        return len(self.calls)

    @property
    def success_count(self) -> int:
        return sum(1 for c in self.calls if c.success)

    @property
    def total_tokens(self) -> int:
        return sum(c.input_tokens + c.output_tokens for c in self.calls)

    @property
    def total_cost_cny(self) -> float:
        return sum(c.estimated_cost_cny for c in self.calls)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_calls if self.total_calls else 0.0


class ProviderError(Exception):
    """provider 调用失败的根异常"""


class ProviderUnavailable(ProviderError):
    """provider 配置不可用（无 API key 等）"""


class ProviderJSONParseError(ProviderError):
    """provider 返回无法解析为 JSON"""


class VisionProvider(ABC):
    """所有视觉 provider 的基类"""

    name: str = "abstract"

    def __init__(self, api_key: Optional[str] = None,
                 timeout_sec: int = 60,
                 max_retries: int = 3,
                 logger: Optional[logging.Logger] = None):
        if not api_key:
            raise ProviderUnavailable(
                f"{self.name} 需要 api_key（请配置环境变量）"
            )
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.logger = logger or logging.getLogger(__name__)
        self.stats = ProviderStats()

    @abstractmethod
    def _raw_call(self, image_b64: str, prompt: str) -> tuple[str, dict]:
        """
        子类实现：调底层 API。
        返回 (response_text, usage_dict)
        usage_dict 含 input_tokens / output_tokens / estimated_cost_cny
        """

    def analyze_image(self, image_path: str | Path, prompt: str) -> str:
        """
        对外主入口（带重试 + 成本统计）。
        image_path: 本地文件路径
        prompt: 文本 prompt
        返回：API 响应文本（应该是 JSON 字符串）
        """
        image_path = Path(image_path)
        if not image_path.exists():
            raise ProviderError(f"图片不存在: {image_path}")

        image_b64 = self._encode_image(image_path)

        @retry(
            retry=retry_if_exception_type(ProviderError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=15),
            reraise=True,
        )
        def _do_call() -> tuple[str, dict]:
            return self._raw_call(image_b64, prompt)

        import time
        t0 = time.time()
        try:
            text, usage = _do_call()
            record = CallRecord(
                provider=self.name,
                image_path=str(image_path),
                prompt_chars=len(prompt),
                success=True,
                duration_sec=time.time() - t0,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                estimated_cost_cny=usage.get("estimated_cost_cny", 0.0),
            )
            self.stats.add(record)
            return text
        except Exception as e:
            record = CallRecord(
                provider=self.name,
                image_path=str(image_path),
                prompt_chars=len(prompt),
                success=False,
                duration_sec=time.time() - t0,
                error=str(e),
            )
            self.stats.add(record)
            raise ProviderError(f"{self.name} 调用失败: {e}") from e

    def analyze_video(self, video_url: str, prompt: str) -> str:
        """
        对外主入口（视频版）。
        video_url: 公网可访问的 mp4/mov URL（本地路径不可用）
        prompt: 文本 prompt
        返回：API 响应文本（应该是 JSON 字符串）

        子类默认未实现，需 override _raw_call_video。
        """
        @retry(
            retry=retry_if_exception_type(ProviderError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=15),
            reraise=True,
        )
        def _do_call() -> tuple[str, dict]:
            return self._raw_call_video(video_url, prompt)

        import time
        t0 = time.time()
        try:
            text, usage = _do_call()
            record = CallRecord(
                provider=self.name,
                image_path=video_url,  # 复用字段记录 URL
                prompt_chars=len(prompt),
                success=True,
                duration_sec=time.time() - t0,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                estimated_cost_cny=usage.get("estimated_cost_cny", 0.0),
            )
            self.stats.add(record)
            return text
        except Exception as e:
            record = CallRecord(
                provider=self.name,
                image_path=video_url,
                prompt_chars=len(prompt),
                success=False,
                duration_sec=time.time() - t0,
                error=str(e),
            )
            self.stats.add(record)
            raise ProviderError(f"{self.name} 视频调用失败: {e}") from e

    def analyze_images(self, image_paths: list[Path | str], prompt: str) -> str:
        """
        对外主入口（多图版）。按顺序传入 N 帧，模型按时间顺序理解。
        用于替代单张三联图 — 单帧分辨率更高 + 时序天然有序。
        """
        paths = [Path(p) for p in image_paths]
        for p in paths:
            if not p.exists():
                raise ProviderError(f"图片不存在: {p}")
        b64s = [self._encode_image(p) for p in paths]

        @retry(
            retry=retry_if_exception_type(ProviderError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=15),
            reraise=True,
        )
        def _do_call() -> tuple[str, dict]:
            return self._raw_call_images(b64s, prompt)

        import time
        t0 = time.time()
        try:
            text, usage = _do_call()
            record = CallRecord(
                provider=self.name,
                image_path=str(paths[0]) + f" (+{len(paths)-1} more)",
                prompt_chars=len(prompt),
                success=True,
                duration_sec=time.time() - t0,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                estimated_cost_cny=usage.get("estimated_cost_cny", 0.0),
            )
            self.stats.add(record)
            return text
        except Exception as e:
            record = CallRecord(
                provider=self.name,
                image_path=str(paths[0]) + f" (+{len(paths)-1} more)",
                prompt_chars=len(prompt),
                success=False,
                duration_sec=time.time() - t0,
                error=str(e),
            )
            self.stats.add(record)
            raise ProviderError(f"{self.name} 多图调用失败: {e}") from e

    def _raw_call_video(self, video_url: str, prompt: str) -> tuple[str, dict]:
        """子类实现：调底层视频 API。默认未实现。"""
        raise ProviderError(f"{self.name} 不支持 video_url 调用")

    def _raw_call_images(self, image_b64s: list[str], prompt: str) -> tuple[str, dict]:
        """子类实现：调底层多图 API。默认 fallback 到 _raw_call（用第一张）。"""
        if not image_b64s:
            raise ProviderError("image_b64s 为空")
        return self._raw_call(image_b64s[0], prompt)

    def _raw_chat(self, prompt: str, max_tokens: int = 4096) -> tuple[str, dict]:
        """子类实现：纯文本 chat 调用（EDL 规划用）。默认未实现。"""
        raise ProviderError(f"{self.name} 不支持 chat")

    def chat(self, prompt: str, max_tokens: int = 4096) -> str:
        """对外主入口（纯文本，无图片）。
        用于 EDL 规划等"输入候选池 JSON + 输出 EDL JSON"的纯文本任务。
        子类通过 override _raw_chat 实现。
        """
        @retry(
            retry=retry_if_exception_type(ProviderError),
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=15),
            reraise=True,
        )
        def _do_call() -> tuple[str, dict]:
            return self._raw_chat(prompt, max_tokens=max_tokens)

        import time
        t0 = time.time()
        try:
            text, usage = _do_call()
            record = CallRecord(
                provider=self.name,
                image_path="(chat)",  # 标识这是无图调用
                prompt_chars=len(prompt),
                success=True,
                duration_sec=time.time() - t0,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                estimated_cost_cny=usage.get("estimated_cost_cny", 0.0),
            )
            self.stats.add(record)
            return text
        except Exception as e:
            record = CallRecord(
                provider=self.name,
                image_path="(chat)",
                prompt_chars=len(prompt),
                success=False,
                duration_sec=time.time() - t0,
                error=str(e),
            )
            self.stats.add(record)
            raise ProviderError(f"{self.name} chat 调用失败: {e}") from e

    @staticmethod
    def _encode_image(image_path: Path, max_size_kb: int = 8000) -> str:
        """
        读图为 base64（按需缩放避免超限）
        国内模型推荐 < 5MB，这里 8MB 上限
        """
        from PIL import Image
        import io

        with Image.open(image_path) as im:
            # 大图缩小
            max_dim = 2048
            if max(im.size) > max_dim:
                ratio = max_dim / max(im.size)
                im = im.resize((int(im.width * ratio), int(im.height * ratio)))
            buf = io.BytesIO()
            fmt = "JPEG" if im.mode != "PNG" else "PNG"
            if fmt == "JPEG" and im.mode in ("RGBA", "P"):
                im = im.convert("RGB")
            im.save(buf, format=fmt, quality=85)
            data = buf.getvalue()

        if len(data) > max_size_kb * 1024:
            # 再压缩
            with Image.open(io.BytesIO(data)) as im:
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=60)
                data = buf.getvalue()

        mime = "image/jpeg" if data[:2] == b"\xff\xd8" else "image/png"
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"


def parse_json_response(text: str) -> Optional[dict]:
    """容错解析 JSON 响应"""
    if not text:
        return None
    # 直接尝试
    try:
        return json.loads(text)
    except Exception:
        pass
    # markdown 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 第一个 {...}
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    # 多行 JSON（含嵌套）
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def validate_schema(data: dict, required_keys: list[str]) -> bool:
    """校验 dict 是否包含必需键"""
    return all(k in data for k in required_keys)
