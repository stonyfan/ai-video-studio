"""
Doubao Vision provider（火山引擎方舟）
OpenAI SDK 兼容模式：base_url=https://ark.cn-beijing.volces.com/api/v3

支持模型（按 endpoint_id 调用）：
- doubao-1.5-vision-pro
- doubao-vision-pro
- doubao-vision-lite
"""
from __future__ import annotations
import os
from typing import Literal, Optional

from openai import OpenAI

from .base import VisionProvider, ProviderError


# 价格表（元/千 token，火山引擎公开价）
DOUBAO_PRICING = {
    "doubao-1.5-vision-pro": {"input": 0.003, "output": 0.003},
    "doubao-vision-pro": {"input": 0.003, "output": 0.003},
    "doubao-vision-lite": {"input": 0.001, "output": 0.001},
}


class DoubaoProvider(VisionProvider):
    """字节豆包视觉"""

    name = "doubao"

    def __init__(self,
                 api_key: Optional[str] = None,
                 model: str = "doubao-1.5-vision-pro",
                 timeout_sec: int = 60,
                 max_retries: int = 3,
                 base_url: Optional[str] = None,
                 mode: Literal["direct", "proxy"] = "direct",
                 auth_token: Optional[str] = None,
                 proxy_base_url: Optional[str] = None):
        if mode == "proxy":
            if not auth_token:
                raise ValueError("proxy 模式需要 auth_token（JWT）")
            api_key = auth_token
            base_url = proxy_base_url or "http://localhost:8000/api/v1/vision"
        else:
            api_key = api_key or os.environ.get("ARK_API_KEY") or os.environ.get("DOUBAO_API_KEY")
            base_url = base_url or "https://ark.cn-beijing.volces.com/api/v3"

        super().__init__(api_key=api_key, timeout_sec=timeout_sec, max_retries=max_retries)
        self.model = model
        self.mode = mode
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_sec)

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
                # 火山方舟也支持 response_format
                extra_body={"response_format": {"type": "json_object"}},
            )
        except Exception as e:
            raise ProviderError(f"Doubao API 调用失败: {e}") from e

        text = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else {}

        pricing = DOUBAO_PRICING.get(self.model, DOUBAO_PRICING["doubao-1.5-vision-pro"])
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = (in_tok * pricing["input"] + out_tok * pricing["output"]) / 1000

        return text, {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_cny": cost,
        }
