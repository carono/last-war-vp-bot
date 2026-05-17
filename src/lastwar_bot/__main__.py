"""Smoke-test the configured providers.

Run:  python -m lastwar_bot
"""

from __future__ import annotations

from .config import AppSettings
from .providers import get_llm_provider
from .providers.base import LLMRequest


def main() -> None:
    settings = AppSettings()
    print(f"LLM provider:    {settings.llm_provider}")
    print(f"Vision provider: {settings.vision_provider}")

    llm = get_llm_provider(settings)
    reply = llm.complete(LLMRequest(prompt="Reply with exactly: ok", max_tokens=8))
    print(f"LLM reply: {reply.strip()!r}")


if __name__ == "__main__":
    main()
