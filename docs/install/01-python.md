# 1. Install Python 3.12

The bot is written for Python 3.12. 3.13 is avoided for now — some CV/ML libraries don't yet ship wheels for it.

## Installation

1. Open [python.org/downloads/windows](https://www.python.org/downloads/windows/).
2. Download the **Windows installer (64-bit)** for the latest 3.12.x.
3. Run the installer. **Tick "Add python.exe to PATH"** on the first screen.
4. Pick `Install Now`.
5. On the final screen, click **"Disable path length limit"** (removes the 260-character limit, which sometimes trips pip).

## Verification

Open a **new** PowerShell window (an existing one won't pick up the updated PATH):

```powershell
python --version
```

You should see something like `Python 3.12.7`. If it reports `3.13.x` or nothing — reinstall with the PATH checkbox and make sure no other versions appear earlier in PATH (check `Apps & features`).

Also check `pip`:

```powershell
python -m pip --version
```

Expected: `pip 24.x ... (python 3.12)`.

## Next

Continue with [step 3 — the bot](03-bot.md). [Ollama](02-ollama.md) is optional and can be installed later.
