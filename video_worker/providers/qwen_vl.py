"""
Qwen-VL provider（阿里云百炼）
OpenAI SDK 兼容模式：base_url=https://dashscope.aliyuncs.com/compatible-mode/v1

支持模型：
- qwen-vl-plus (¥0.008/千 token)
- qwen-vl-max (¥0.02/千 token)
- qwen2.5-vl-72b-instruct 等
"""
from __future__ import annotations
import os
from typing import Optional

from openai import OpenAI

from .base import VisionProvider, ProviderError


# 价格表（元/千 token，阿里云公开价）
QWEN_VL_PRICING = {
    "qwen-vl-plus": {"input": 0.008, "output": 0.008},
    "qwen-vl-max": {"input": 0.020, "output": 0.020},
    "qwen2.5-vl-72b-instruct": {"input": 0.008, "output": 0.008},
    "qwen2.5-vl-7b-instruct": {"input": 0.002, "output": 0.002},
}


class QwenVLProvider(VisionProvider):
    """阿里 Qwen-VL"""

    name = "qwen-vl"

    def __init__(self,
                 api_key: Optional[str] = None,
                 model: str = "qwen-vl-plus",
                 timeout_sec: int = 60,
                 max_retries: int = 3,
                 base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        api_key = api_key or os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("QWEN_VL_API_KEY")
        super().__init__(api_key=api_key, timeout_sec=timeout_sec, max_retries=max_retries)
        self.model = model
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
                # Qwen-VL 支持响应格式约束
                extra_body={"response_format": {"type": "json_object"}},
            )
        except Exception as e:
            raise ProviderError(f"Qwen-VL API 调用失败: {e}") from e

        text = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else {}

        # 计算成本
        pricing = QWEN_VL_PRICING.get(self.model, QWEN_VL_PRICING["qwen-vl-plus"])
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = (in_tok * pricing["input"] + out_tok * pricing["output"]) / 1000

        return text, {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_cny": cost,
        }
