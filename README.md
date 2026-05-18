# Last War Bot (v2)

Automation for the Last War PC client. A hybrid of computer vision and LLM: fast CV for routine work (template matching, OCR), VLM/LLM for screen classification, scenario planning, and recognising unknown situations.

Supports both local models (via [Ollama](https://ollama.com)) and cloud services exposing an OpenAI-compatible API (OpenAI, Anthropic, Groq, Together, OpenRouter, self-hosted llama.cpp, vLLM, etc.). Provider selection is driven by environment variables.

**Status:** active rewrite. The old Lua/UOPilot version lives on the `master` branch; its documentation is preserved under [`docs/legacy-ru/`](docs/legacy-ru/) and [`docs/legacy-en/`](docs/legacy-en/) as a feature reference.

## Installation

See [`docs/install/`](docs/install/README.md) — step-by-step Windows guides for Python, Ollama, and the bot itself.

## Architecture

See [`docs/architecture.md`](docs/architecture.md).

## Smoke test

After installation:

```powershell
.venv\Scripts\activate
python -m lastwar_bot
```

The script verifies the connection to the configured LLM provider and prints a short model reply.
