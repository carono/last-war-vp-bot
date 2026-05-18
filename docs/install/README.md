# Installation (Windows)

These guides target Windows 10/11. All commands are for PowerShell. Go through the steps in order.

1. [Python 3.12](01-python.md) — interpreter and `pip`.
2. [The bot](03-bot.md) — clone the repository, virtual environment, dependencies, smoke test in `stub` mode (no external models needed).
3. [Ollama + models](02-ollama.md) — optional, for moving from the stub to local LLM/VLM. Safe to defer.

During development the bot runs against a stub provider; the real model is wired in later by editing `.env` — either Ollama locally or any OpenAI-compatible cloud service.

## System requirements

- Windows 10/11 (64-bit).
- 8+ GB RAM (16 GB comfortable).
- NVIDIA GPU with 8+ GB VRAM — for a local VLM. Without a GPU, use a cloud provider.
- Last War PC client installed (needed for the bot to do anything; not required during initial setup).
