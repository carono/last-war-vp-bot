# Installation (Windows)

These guides target Windows 10/11.

**The short way — [`install.bat`](00-installer.md).** Unpack the archive
wherever you like and run `install.bat` from inside it: that folder is the
installation, and the installer puts Python 3.12, Git and the dependencies
around it and the panel on the Desktop. Nothing has to be installed first, and
running it again repairs a half-finished install. Everything below is the same
work done by hand.

The manual route, in order (all commands are for PowerShell):

1. [Python 3.12](01-python.md) — interpreter and `pip`.
2. [The bot](03-bot.md) — clone the repository, virtual environment, dependencies, smoke test in `stub` mode (no external models needed).
3. [Ollama + models](02-ollama.md) — optional, for moving from the stub to local LLM/VLM. Safe to defer.

During development the bot runs against a stub provider; the real model is wired in later by editing `.env` — either Ollama locally or any OpenAI-compatible cloud service.

## System requirements

- Windows 10/11 (64-bit).
- 8+ GB RAM (16 GB comfortable).
- NVIDIA GPU with 8+ GB VRAM — for a local VLM. Without a GPU, use a cloud provider.
- Last War PC client installed (needed for the bot to do anything; not required during initial setup).
