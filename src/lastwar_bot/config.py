"""Application configuration loaded from environment / `.env`.

Provider selection is split into two independent axes:
- `LLM_PROVIDER`    — for text-only planning calls
- `VISION_PROVIDER` — for screen classification / VLM calls

Each provider has its own settings block with a unique env prefix.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["ollama", "openai_compat"]


class OllamaSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OLLAMA_", env_file=".env", extra="ignore")

    base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:7b-instruct-q4_K_M"
    vision_model: str = "qwen2-vl:2b"


class OpenAICompatSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPENAI_", env_file=".env", extra="ignore")

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    vision_model: str = "gpt-4o-mini"


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: ProviderName = "ollama"
    vision_provider: ProviderName = "ollama"

    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    openai_compat: OpenAICompatSettings = Field(default_factory=OpenAICompatSettings)
