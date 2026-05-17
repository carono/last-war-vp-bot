"""Abstract interfaces for LLM and Vision-Language providers.

Concrete backends live next to this module. Selection happens via config
(see `lastwar_bot.config.AppSettings`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class LLMRequest:
    prompt: str
    system: str | None = None
    max_tokens: int = 512


@dataclass(slots=True)
class VisionRequest:
    image: bytes | Path
    prompt: str
    max_tokens: int = 256


class LLMProvider(ABC):
    """Text-only LLM (planning, decomposition, summarisation)."""

    @abstractmethod
    def complete(self, req: LLMRequest) -> str: ...


class VisionProvider(ABC):
    """Vision-Language model (image + prompt → text)."""

    @abstractmethod
    def describe(self, req: VisionRequest) -> str: ...
