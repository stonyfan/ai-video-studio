"""
GLM-4V provider（智谱 AI / BigModel）
OpenAI SDK 兼容模式：base_url=https://open.bigmodel.cn/api/paas/v4/

支持模型：
- glm-4.6v     (¥0.001/千 token 入，¥0.003/千 token 出；支持 video_url)
- glm-4v-plus  (¥0.01/千 token 入，¥0.05/千 token 出)
- glm-4v-flash (免费 / 限速)
- glm-4v       (¥0.05 入，¥0.05 出)

支持 2 种模式：
- direct（A 模式默认）：用户配的 API key，直连智谱
- proxy（C 模式预留）：用 JWT 当 key，调后端 model_proxy
"""
from __future__ import annotations
import logging
import os
from typing import Literal, Optional

from openai import OpenAI

from .base import VisionProvider, ProviderError


# 价格表（元/千 token，智谱公开价）
GLM_PRICING = {
    "glm-4.6v": {"input": 0.001, "output": 0.003},
    "glm-4v-plus": {"input": 0.010, "output": 0.050},
    "glm-4v": {"input": 0.050, "output": 0.050},
    "glm-4v-flash": {"input": 0.0, "output": 0.0},
    # 纯文本模型（用作 EDL fallback）
    "glm-4-plus": {"input": 0.050, "output": 0.050},
    "glm-4-flash": {"input": 0.001, "output": 0.001},
}

# video_url 必须用 glm-4.6v（glm-4v-plus 不支持视频）
GLM_VIDEO_MODEL = "glm-4.6v"
# 多图调用上限：glm-4v-plus / glm-4v 仅 5 图，glm-4.6v 支持 12 图
GLM_MULTI_IMAGE_MODEL = "glm-4.6v"
GLM_MULTI_IMAGE_THRESHOLD = 5  # 图数 > 此值自动切 glm-4.6v


class GLMProvider(VisionProvider):
    """智谱 GLM-4V"""

    name = "glm"

    def __init__(self,
                 api_key: Optional[str] = None,
                 model: str = "glm-4v-plus",
                 timeout_sec: int = 60,
                 max_retries: int = 3,
                 base_url: Optional[str] = None,
                 mode: Literal["direct", "proxy"] = "direct",
                 auth_token: Optional[str] = None,
                 proxy_base_url: Optional[str] = None,
                 video_model: Optional[str] = None,
                 logger: Optional[logging.Logger] = None):
        if mode == "proxy":
            if not auth_token:
                raise ValueError("proxy 模式需要 auth_token（JWT）")
            api_key = auth_token
            base_url = proxy_base_url or "http://localhost:8000/api/v1/vision/glm"
        else:
            api_key = api_key or os.environ.get("ZHIPU_API_KEY") or os.environ.get("GLM_API_KEY")
            base_url = base_url or "https://open.bigmodel.cn/api/paas/v4/"

        super().__init__(api_key=api_key, timeout_sec=timeout_sec,
                         max_retries=max_retries, logger=logger)
        self.model = model
        self.mode = mode
        # video_url 调用强制走 glm-4.6v（除非显式覆盖）
        self.video_model = video_model or GLM_VIDEO_MODEL
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
                # 智谱兼容 OpenAI response_format
                extra_body={"response_format": {"type": "json_object"}},
            )
        except Exception as e:
            raise ProviderError(f"GLM API 调用失败: {e}") from e

        return self._extract_response(resp, self.model)

    def _raw_call_images(self, image_b64s: list[str], prompt: str) -> tuple[str, dict]:
        """多图调用：N 张 image_url 按顺序传入 + text prompt。
        GLM-4V 系列原生支持 content 数组多 image_url，时序由数组顺序保留。

        自动切模型：图数 > 5 时 glm-4v-plus / glm-4v 会报 1210（图片数超限），
        此时强制切 glm-4.6v（支持 12 图）。video_worker/frame_extract 抽帧自适应 5-12 张，
        旧 model 无法承载。
        """
        n_imgs = len(image_b64s)
        use_model = self.model
        if n_imgs > GLM_MULTI_IMAGE_THRESHOLD and self.model != GLM_MULTI_IMAGE_MODEL:
            if self.logger:
                self.logger.info(
                    f"[glm] 多图 {n_imgs} 张超过 {GLM_MULTI_IMAGE_THRESHOLD}，"
                    f"自动从 {self.model} 切到 {GLM_MULTI_IMAGE_MODEL}"
                )
            use_model = GLM_MULTI_IMAGE_MODEL
        content = [{"type": "image_url", "image_url": {"url": b64}} for b64 in image_b64s]
        content.append({"type": "text", "text": prompt})
        try:
            resp = self.client.chat.completions.create(
                model=use_model,
                messages=[{"role": "user", "content": content}],
                extra_body={"response_format": {"type": "json_object"}},
            )
        except Exception as e:
            raise ProviderError(f"GLM 多图 API 调用失败: {e}") from e
        return self._extract_response(resp, use_model)

    def _raw_chat(self, prompt: str, max_tokens: int = 4096) -> tuple[str, dict]:
        """纯文本 chat 调用（EDL 规划用）。复用同一 client + model。
        messages content 是 plain string，不传 image。
        EDL prompt 较大（~6KB）+ max_tokens 大，需要更长超时。

        glm-5 系列默认开 thinking 模式，会烧大量 reasoning_tokens。
        对 EDL 这种结构化任务，关掉 thinking 省成本 + 避免输出空响应。
        """
        import time
        t0 = time.time()
        extra_body: dict = {"response_format": {"type": "json_object"}}
        # glm-5/5.2/5-turbo 等关 thinking
        if self.model.startswith("glm-5"):
            extra_body["thinking"] = {"type": "disabled"}
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                extra_body=extra_body,
                max_tokens=max_tokens,
                timeout=180,  # EDL 规划比单图分析耗时，单独覆盖（秒）
            )
        except Exception as e:
            raise ProviderError(f"GLM chat API 调用失败 (耗时 {time.time()-t0:.1f}s): {e}") from e
        return self._extract_response(resp, self.model)

    def _raw_call_video(self, video_url: str, prompt: str) -> tuple[str, dict]:
        """video_url 调用：必须用 glm-4.6v（glm-4v-plus 不支持视频理解）。

        参考 https://docs.bigmodel.cn/cn/guide/models/vlm/glm-4.6v
        """
        try:
            resp = self.client.chat.completions.create(
                model=self.video_model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": video_url}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                extra_body={"response_format": {"type": "json_object"}},
            )
        except Exception as e:
            raise ProviderError(f"GLM video API 调用失败: {e}") from e

        return self._extract_response(resp, self.video_model)

    def _extract_response(self, resp, model_name: str) -> tuple[str, dict]:
        """从 OpenAI 风格响应里拿 text + usage + 成本"""
        text = resp.choices[0].message.content or ""
        usage = resp.usage.model_dump() if resp.usage else {}

        pricing = GLM_PRICING.get(model_name, GLM_PRICING["glm-4v-plus"])
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = (in_tok * pricing["input"] + out_tok * pricing["output"]) / 1000

        return text, {
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "estimated_cost_cny": cost,
        }
