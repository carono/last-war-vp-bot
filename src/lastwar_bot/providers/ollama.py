"""Local Ollama provider (HTTP).

Talks to an Ollama daemon (default `http://127.0.0.1:11434`). The same model
can be used as text-only LLM or VLM depending on what was pulled.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from .base import LLMProvider, LLMRequest, VisionProvider, VisionRequest


class OllamaProvider(LLMProvider, VisionProvider):
    def __init__(self, model: str, base_url: str = "http://127.0.0.1:11434", timeout: float = 60.0) -> None:
        self.model = model
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def complete(self, req: LLMRequest) -> str:
        payload: dict = {
            "model": self.model,
            "prompt": req.prompt,
            "stream": False,
            "options": {"num_predict": req.max_tokens},
        }
        if req.system:
            payload["system"] = req.system
        resp = self._client.post("/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["response"]

    def describe(self, req: VisionRequest) -> str:
        image_bytes = req.image.read_bytes() if isinstance(req.image, Path) else req.image
        payload = {
            "model": self.model,
            "prompt": req.prompt,
            "images": [base64.b64encode(image_bytes).decode()],
            "stream": False,
            "options": {"num_predict": req.max_tokens},
        }
        resp = self._client.post("/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["response"]
