"""Provider factories — instantiate configured backends by name."""

from __future__ import annotations

from ..config import AppSettings, ProviderName
from .base import LLMProvider, VisionProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .stub import StubProvider


def get_llm_provider(settings: AppSettings) -> LLMProvider:
    return _build(settings.llm_provider, settings, kind="llm")


def get_vision_provider(settings: AppSettings) -> VisionProvider:
    return _build(settings.vision_provider, settings, kind="vision")


def _build(name: ProviderName, settings: AppSettings, *, kind: str):
    if name == "stub":
        return StubProvider()
    if name == "ollama":
        model = settings.ollama.llm_model if kind == "llm" else settings.ollama.vision_model
        return OllamaProvider(model=model, base_url=settings.ollama.base_url)
    if name == "openai_compat":
        model = settings.openai_compat.llm_model if kind == "llm" else settings.openai_compat.vision_model
        return OpenAICompatProvider(
            model=model,
            api_key=settings.openai_compat.api_key,
            base_url=settings.openai_compat.base_url,
        )
    raise ValueError(f"Unknown provider: {name!r}")


__all__ = [
    "LLMProvider",
    "VisionProvider",
    "get_llm_provider",
    "get_vision_provider",
]
