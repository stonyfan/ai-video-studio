"""
Zai 视觉 provider

注意：zai 通过 MCP server 调用（mcp__zai-mcp-server__analyze_image）。
本 provider 假设调用方能访问 MCP（在 Claude Code / 类似环境运行）。

阶段 2 接入后端模型代理后，将改为 HTTP 调用，不再依赖 MCP。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any


class ZaiProvider:
    """zai MCP provider"""

    name = "zai"

    def __init__(self):
        # 检测 MCP 可用性
        try:
            # 在 Claude Code 环境，mcp 工具作为内置函数可用
            # 在其他环境（CLI/CI），需要通过 HTTP 代理调用 zai MCP server
            self._mcp_available = self._detect_mcp()
        except Exception:
            self._mcp_available = False

    def _detect_mcp(self) -> bool:
        """探测 MCP 是否可用（占位）"""
        # 实际实现需要检查 mcp__zai-mcp-server__analyze_image 是否在工具列表
        # 在非 Claude Code 环境（如纯 Python CLI），应该走后端模型代理
        return False  # 默认 False，需要外部注入

    def analyze_image(self, image_path: str, prompt: str) -> str:
        """
        调 zai 视觉分析。
        在 Claude Code 环境，由调用方注入 mcp 工具。
        在生产环境，由后端模型代理调用。
        """
        if self._mcp_available:
            # 由外部注入的 mcp 调用
            return self._mcp_call(image_path, prompt)
        raise RuntimeError(
            "zai MCP 不可用。在 Claude Code 环境外运行时，请配置后端模型代理（阶段 3）。"
        )

    def _mcp_call(self, image_path: str, prompt: str) -> str:
        # 由外部注入
        raise NotImplementedError(
            "MCP 调用需由外部注入。在 Claude Code 中由 process_job 内联调用 mcp 工具。"
        )


class MockProvider:
    """测试用 mock provider，返回固定 JSON"""

    name = "mock"

    def __init__(self, response: str = None):
        self.response = response or (
            '{"best_frame": "mid", "cut_duration": 0.8, '
            '"best_moment": "测试瞬时", "main_object": "测试物体", '
            '"action_type": "pouring"}'
        )

    def analyze_image(self, image_path: str, prompt: str) -> str:
        return self.response
