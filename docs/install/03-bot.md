# 3. Install the bot

This step assumes [Python 3.12](01-python.md) is installed. **Ollama is not required at this stage** — the bot starts in dev mode with a stub provider that returns canned answers. A real provider (Ollama / cloud) is wired in later by editing `.env`.

## Get the source

```powershell
cd $HOME
git clone https://github.com/carono/last-war-vp-bot.git
cd last-war-vp-bot
git checkout v2
```

(If the repository is already cloned — `cd` into it and `git checkout v2`.)

## Virtual environment and dependencies

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

The final command (`pip install -e .`) attaches the `lastwar_bot` package from `src/` in editable mode. Without it, `python -m lastwar_bot` complains with `No module named lastwar_bot`.

> If PowerShell blocks `Activate.ps1` — run once: `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.

## Smoke test (no external models)

Without a `.env` the bot defaults to `stub` mode:

```powershell
python -m lastwar_bot
```

Expected output:

```
LLM provider:    stub
Vision provider: stub
LLM reply: "[stub LLM] prompt='Reply with exactly: ok'; reply: ok"
```

This confirms the package is installed, the config is read, and the provider factory works.

## Hooking up a real model

When we reach actual integration — copy the template:

```powershell
copy .env.example .env
notepad .env
```

The file holds two independent provider settings: LLM (planning) and Vision. Both default to `ollama`.

### Option A: Ollama, fully local

Install [Ollama](02-ollama.md), then in `.env`:

```ini
LLM_PROVIDER=ollama
VISION_PROVIDER=ollama
OLLAMA_LLM_MODEL=qwen2.5:7b-instruct-q4_K_M
OLLAMA_VISION_MODEL=qwen2-vl:2b
```

### Option B: Cloud provider (OpenAI / Anthropic-compat / Groq / OpenRouter / …)

```ini
LLM_PROVIDER=openai_compat
VISION_PROVIDER=openai_compat
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_LLM_MODEL=gpt-4o-mini
OPENAI_VISION_MODEL=gpt-4o-mini
```

For Groq / Together / OpenRouter / Anthropic / a local `llama.cpp` server, change `OPENAI_BASE_URL` and the model name; use the matching API key.

### Option C: Mix

For example, cloud LLM (better planning) plus local Ollama vision:

```ini
LLM_PROVIDER=openai_compat
VISION_PROVIDER=ollama
```

## Common problems

- **`No module named lastwar_bot`** — you skipped `pip install -e .` inside the activated `.venv`.
- **`ConnectError: All connection attempts failed`** with `LLM_PROVIDER=ollama` — Ollama is not running or not installed. Check the tray icon, or switch to `stub` / `openai_compat`.
- **`401 Unauthorized`** with `openai_compat` — missing or invalid `OPENAI_API_KEY`.
- **`model "..." not found`** in Ollama — the model wasn't pulled. Run `ollama pull <name>`.
- **`Activate.ps1 cannot be loaded because running scripts is disabled`** — `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`.
