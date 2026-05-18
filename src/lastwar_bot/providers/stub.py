"""Stub provider — development mode без внешних LLM/VLM сервисов.

Возвращает canned-ответы: позволяет собирать и тестировать пайплайн
(захват окна → классификация → скилл) до того, как подключим реальную
модель (Ollama / cloud). Для настоящих семантических запросов на этапе
разработки используется ручной цикл: разработчик показывает скриншот и
вопрос Claude в чате, ответ Claude применяется как результат VLM.
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
