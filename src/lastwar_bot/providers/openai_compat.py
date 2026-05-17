"""OpenAI-compatible HTTP provider.

Works with any service exposing the OpenAI Chat Completions API:
OpenAI, Groq, Together, OpenRouter, Anthropic (via /v1 compat endpoint),
local llama.cpp server, vLLM, etc.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from .base import LLMProvider, LLMRequest, VisionProvider, VisionRequest


class OpenAICompatProvider(LLMProvider, VisionProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ) -> None:
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers)

    def complete(self, req: LLMRequest) -> str:
        messages: list[dict] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})
        payload = {"model": self.model, "messages": messages, "max_tokens": req.max_tokens}
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    def describe(self, req: VisionRequest) -> str:
        image_bytes = req.image.read_bytes() if isinstance(req.image, Path) else req.image
        b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": req.prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
            "max_tokens": req.max_tokens,
        }
        resp = self._client.post("/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
