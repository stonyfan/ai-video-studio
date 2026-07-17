"""
Doubao Vision provider（火山引擎方舟）
OpenAI SDK 兼容模式：base_url=https://ark.cn-beijing.volces.com/api/v3

调用方式：传"接入点 ep- ID"作为 model 参数（不是模型名）。
Doubao-Seed-2.1-pro 是多模态统一模型，同一个 ep- ID 可同时用于：
- 视觉分析（带 image_url）
- 纯文本 EDL 规划（无图）
"""
from __future__ import annotations
import logging
import os
from typing import Literal, Optional

from openai import OpenAI

from .base import VisionProvider, ProviderError


# 价格表（元/千 token，火山引擎公开价）
DOUBAO_PRICING = {
    "doubao-1.5-vision-pro": {"input": 0.003, "output": 0.009},
    "doubao-vision-pro": {"input": 0.003, "output": 0.009},
    "doubao-vision-lite": {"input": 0.001, "output": 0.002},
    "doubao-seed-2.1-pro": {"input": 0.004, "output": 0.016},
    "_default": {"input": 0.004, "output": 0.016},  # ep- ID 默认走 Seed 价格
}


class DoubaoProvider(VisionProvider):
    """字节豆包视觉"""

    name = "doubao"

    def __init__(self,
                 api_key: Optional[str] = None,
                 model: str = "ep-20260712162006-kcfdm",  # 默认 Doubao-Seed-2.1-pro 接入点
                 timeout_sec: int = 60,
                 max_retries: int = 3,
                 base_url: Optional[str] = None,
                 mode: Literal["direct", "proxy"] = "direct",
                 auth_token: Optional[str] = None,
                 proxy_base_url: Optional[str] = None,
                 enable_thinking: bool = False,
                 logger: Optional[logging.Logger] = None):
        if mode == "proxy":
            if not auth_token:
                raise ValueError("proxy 模式需要 auth_token（JWT）")
            api_key = auth_token
            base_url = proxy_base_url or "http://localhost:8000/api/v1/vision/doubao"
        else:
            api_key = api_key or os.environ.get("ARK_API_KEY") or os.environ.get("DOUBAO_API_KEY")
            base_url = base_url or "https://ark.cn-beijing.volces.com/api/v3"

        super().__init__(api_key=api_key, timeout_sec=timeout_sec,
                         max_retries=max_retries, logger=logger)
        self.model = model
        self.mode = mode
        self.enable_thinking = enable_thinking

        # doubao-agent-plan: base_url 由 get_provider 注入为 /api/plan/v3（订阅专用）
        # vision + chat 都走订阅 base url + 订阅 key（订阅套餐 doubao-seed-2.0-pro 支持多模态）
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_sec)
        self.chat_client = self.client

    def _extra_body(self, json_mode: bool = True) -> dict:
        """统一 extra_body：json mode + thinking 控制。
        Doubao-Seed 默认开 thinking，会烧大量 reasoning_tokens。
        EDL 这种结构化任务默认关掉；如需开启，构造时传 enable_thinking=True。
        """
        eb: dict = {}
        if json_mode:
            eb["response_format"] = {"type": "json_object"}
        is_seed = self.model.startswith("ep-") or "seed" in self.model.lower()
        if is_seed and not self.enable_thinking:
            eb["thinking"] = {"type": "disabled"}
        return eb

    def _raw_call(self, image_b64: str, prompt: str) -> tuple[str, dict]:
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_b64}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                extra_body=self._extra_body(),
            )
        except Exception as e:
            raise ProviderError(f"Doubao API 调用失败: {e}") from e
        return self._extract_response(resp)

    def _raw_call_images(self, image_b64s: list[str], prompt: str) -> tuple[str, dict]:
        """多图调用：Doubao-Seed 原生支持 content 数组多 image_url。"""
        if not image_b64s:
            raise ProviderError("image_b64s 为空")
        content = [{"type": "image_url", "image_url": {"url": b64}} for b64 in image_b64s]
        content.append({"type": "text", "text": prompt})
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                extra_body=self._extra_body(),
            )
        except Exception as e:
            raise ProviderError(f"Doubao 多图 API 调用失败: {e}") from e
        return self._extract_response(resp)

    def _raw_chat(self, prompt: str, max_tokens: int = 4096) -> tuple[str, dict]:
        """纯文本 chat（EDL 规划用）。"""
        import time
        t0 = time.time()
        try:
            resp = self.chat_client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                extra_body=self._extra_body(),
                max_tokens=max_tokens,
                timeout=180,
            )
        except Exception as e:
            raise ProviderError(f"Doubao chat API 调用失败 (耗时 {time.time()-t0:.1f}s): {e}") from e
        return self._extract_response(resp)

    def _extract_response(self, resp) -> tuple[str, dict]:
        text = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else {}

        pricing = DOUBAO_PRICING.get(self.model, DOUBAO_PRICING["_default"])
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = (in_tok * pricing["input"] + out_tok * pricing["output"]) / 1000

        return text, {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_cny": cost,
        }
