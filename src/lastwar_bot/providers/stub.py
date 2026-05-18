"""Stub provider — development mode without external LLM/VLM services.

Returns canned responses so the rest of the pipeline (capture → classify →
skill) can be built and tested before a real backend is wired in. For
genuine semantic calls during development, the developer-in-the-loop
workflow is used: paste the screenshot and the question into the chat,
take the assistant's reply as the VLM result.
"""

from __future__ import annotations

from pathlib import Path

from .base import LLMProvider, LLMRequest, VisionProvider, VisionRequest


class StubProvider(LLMProvider, VisionProvider):
    def complete(self, req: LLMRequest) -> str:
        return f"[stub LLM] prompt={req.prompt[:60]!r}; reply: ok"

    def describe(self, req: VisionRequest) -> str:
        if isinstance(req.image, Path):
            size = req.image.stat().st_size
        else:
            size = len(req.image)
        return f"[stub VLM] image={size}B; prompt={req.prompt[:60]!r}; reply: ok"
