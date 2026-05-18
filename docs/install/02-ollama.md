# 2. Install Ollama and models (optional)

[Ollama](https://ollama.com) is a local LLM/VLM runner. One-command management, automatic GPU detection (CUDA on NVIDIA), everything stored in one folder.

> This step is **not required during development**: the bot starts with a stub provider that needs no external services. Install Ollama when you reach real model integration, or if you want to use a local VLM from the start instead of cloud. The alternative is a cloud service via an OpenAI-compatible API (see [step 3, option B](03-bot.md#option-b-cloud-provider-openai--anthropic-compat--groq--openrouter)).

## Install

1. Open [ollama.com/download/windows](https://ollama.com/download/windows).
2. Download `OllamaSetup.exe` and run it.
3. After installation Ollama starts automatically and listens on `http://127.0.0.1:11434`. A llama icon appears in the system tray.

## Verify the daemon

In PowerShell:

```powershell
curl http://127.0.0.1:11434/api/tags
```

You should get JSON with the model list (empty at first: `{"models":[]}`). If the connection fails — open the tray menu and confirm Ollama is running.

## Pulling models

For an 8 GB VRAM GPU (e.g. RTX 2060), quantised models up to 7B fit. Recommended starting set:

```powershell
# Text model for planning (~4.5 GB)
ollama pull qwen2.5:7b-instruct-q4_K_M

# Vision-Language model for screen classification (~2 GB)
ollama pull qwen2-vl:2b
```

Downloads come from the CDN and take a few minutes each.

Verify the models are present:

```powershell
ollama list
```

Quick text-model probe:

```powershell
ollama run qwen2.5:7b-instruct-q4_K_M "Reply with a single word: ok"
```

## What to pick next

Browse [ollama.com/library](https://ollama.com/library) for more models. Guidelines for our architecture:

- **LLM (text):** something instruct-tuned, 7B Q4 (Qwen2.5, Llama 3.1, Mistral). The smarter, the cleaner the plan.
- **VLM (vision):** `qwen2-vl:2b` — fast and accurate for UI tasks. Alternatives: `minicpm-v` (~8B, heavier, more accurate), `moondream` (~1.8B, very fast, weaker).

The model names then go into the bot's `.env` (next step).

## Next

[Step 3 — installing the bot](03-bot.md).
