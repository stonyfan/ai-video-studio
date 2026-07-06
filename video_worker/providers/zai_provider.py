"""
Zai 视觉 provider（默认）

zai 通过 MCP server 调用（mcp__zai-mcp-server__analyze_image）。
本 provider 仅在 Claude Code 等支持 MCP 的环境中工作。
生产环境请用 qwen-vl 或 doubao provider。
"""
from __future__ import annotations
import logging
from typing import Any, Optional

from .base import VisionProvider


class ZaiProvider(VisionProvider):
    """
    zai MCP provider
    本地 MCP 调用，不走 HTTP，因此没有 cost 统计
    """

    name = "zai"

    def __init__(self,
                 mcp_caller: Any = None,
                 logger: Optional[logging.Logger] = None):
        # zai 不需要 api_key（MCP 内置认证）
        # 临时绕过基类的 api_key 检查
        self._mcp_caller = mcp_caller
        self.logger = logger or logging.getLogger(__name__)
        # 不调 super().__init__（zai 走 MCP）
        self.timeout_sec = 60
        self.max_retries = 3
        from .base import ProviderStats
        self.stats = ProviderStats()

    def _raw_call(self, image_b64: str, prompt: str) -> tuple[str, dict]:
        raise NotImplementedError(
            "ZaiProvider 不走 _raw_call，analyze_image 已重写"
        )

    def analyze_image(self, image_path, prompt: str) -> str:
        """通过外部注入的 mcp_caller 调用"""
        if self._mcp_caller is None:
            raise RuntimeError(
                "ZaiProvider 需要外部注入 mcp_caller（在 Claude Code 中由 process_job 注入）。"
                "生产环境请改用 qwen-vl 或 doubao provider。"
            )
        import time
        t0 = time.time()
        try:
            text = self._mcp_caller(str(image_path), prompt)
            from .base import CallRecord
            self.stats.add(CallRecord(
                provider=self.name,
                image_path=str(image_path),
                prompt_chars=len(prompt),
                success=True,
                duration_sec=time.time() - t0,
            ))
            return text
        except Exception as e:
            from .base import CallRecord
            self.stats.add(CallRecord(
                provider=self.name,
                image_path=str(image_path),
                prompt_chars=len(prompt),
                success=False,
                duration_sec=time.time() - t0,
                error=str(e),
            ))
            raise


class MockProvider(VisionProvider):
    """测试用 mock，返回固定 JSON"""

    name = "mock"

    def __init__(self, response: Optional[str] = None):
        # 绕过基类 api_key 检查
        self.timeout_sec = 60
        self.max_retries = 3
        self.logger = logging.getLogger(__name__)
        from .base import ProviderStats
        self.stats = ProviderStats()
        self.response = response or (
            '{"best_frame": "mid", "cut_duration": 0.8, '
            '"best_moment": "测试瞬时", "main_object": "测试物体", '
            '"action_type": "pouring"}'
        )

    def _raw_call(self, image_b64: str, prompt: str) -> tuple[str, dict]:
        return self.response, {
            "input_tokens": 100,
            "output_tokens": 50,
            "estimated_cost_cny": 0.0,
        }

    def analyze_image(self, image_path, prompt: str) -> str:
        return self.response
