# Last War Bot (v2)

Automation for the Last War PC client. A hybrid of computer vision and LLM: fast CV for routine work (template matching, OCR), VLM/LLM for screen classification, scenario planning, and recognising unknown situations.

Supports both local models (via [Ollama](https://ollama.com)) and cloud services exposing an OpenAI-compatible API (OpenAI, Anthropic, Groq, Together, OpenRouter, self-hosted llama.cpp, vLLM, etc.). Provider selection is driven by environment variables.

**Status:** active rewrite. The old Lua/UOPilot version lives on the `master` branch; its documentation is preserved under [`docs/legacy-ru/`](docs/legacy-ru/) and [`docs/legacy-en/`](docs/legacy-en/) as a feature reference.

## Installation

Download **[`install.bat`](install.bat)** and double-click it: it installs Git and
Python 3.12, clones this repository, installs the dependencies and puts the
control panel on the Desktop — on a machine with none of that already there.
Details and options: [`docs/install/00-installer.md`](docs/install/00-installer.md).

Prefer to do it by hand? [`docs/install/`](docs/install/README.md) has the
step-by-step Windows guides for Python, Ollama and the bot itself.

## Architecture

See [`docs/architecture.md`](docs/architecture.md).

## Feature status

What the bot can do today, against the legacy feature list and the daily
routine: [`docs/farming.md`](docs/farming.md)
(на русском — [`docs/farming.ru.md`](docs/farming.ru.md)).

## Running

The control panel — the window everything is driven from — opens with
**`panel.bat`**, which is what the Desktop shortcut points at. **`update.bat`**
next to it pulls the latest sources and refreshes the dependencies.

`run.bat` is the older, venv-based launcher for the vision UI below.

Or from a terminal:

```powershell
python -m panel                  # the control panel
python -m panel --profile second # …on another profile
```

The vision UI, from an activated venv:

```powershell
.venv\Scripts\activate

# Provider smoke test — prints a short reply from the configured LLM.
python -m lastwar_bot

# Control UI — Tk window with Start / Stop. Each tick captures the
# Last War window and logs basic stats.
python -m lastwar_bot.ui
```
