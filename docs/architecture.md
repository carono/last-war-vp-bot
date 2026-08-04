# Architecture (v2)

> **Read this alongside the reality.** This file captures the *original* v2 design
> intent. The canonical, up-to-date architecture and orientation now live in
> [`AGENTS.md`](../AGENTS.md); the honest feature-by-feature status is in
> [`farming.md`](farming.md). Two things below never got built as drawn: the
> **LLM planner** and the **VLM executor** loop. In practice the bot today acts
> mainly through the game's **own Lua VM** (the warm daemon, `tools/lua_daemon.py`)
> and the decoded network protocol, with the CV/OCR + DSL layer used only where no
> Lua route exists. The planner/executor below remain an open goal, not a
> description of what runs.

## Separation of concerns

The main pain point of v1 (Lua/UOPilot) was pixel-colour navigation: any UI update broke the scripts. v2 splits the problem into two layers:

- **Python — "hands and eyes".** Window capture, template matching (OpenCV), OCR, mouse/keyboard input, state verification, retry/recovery. These primitives are predictable, fast (milliseconds), and deterministic.
- **AI — "semantic glue".** When we need to understand "what's on the screen right now", or to decompose a high-level goal ("collect resources at the base") into a sequence of known-good actions, we ask a VLM/LLM. The AI is called sparingly, on demand, not on every tick.

Top-level flow: `"collect resources at the base"` → **planner** turns it into `[open_base, find_resource_icons, click_each, return]` → **executor** runs each step through pre-built Python skills → after each step it compares the expected screen with the actual one (via the classifier) → on mismatch, it triggers recovery.

## High-level skills are scripts, not Python

The skill catalogue lives in **`src/lastwar_bot/actions/*.md`** as a small
declarative DSL — readable for humans, writable by an LLM. Example
(`go_to_base.md`):

```
# Navigate to the Base screen if we're not already there.

IF screen != base
    CALL click_base_button
    WAIT screen == base WITHIN 10s
```

A tiny interpreter (`script_engine.py`) parses these files and calls
into low-level Python primitives (find_window, SceneIndex.find_sift,
click, identify_screen, …) as well as Lua-VM routes (`TAP`, `LUA`,
`GAME`, `JUMP`, …). Only those primitives stay in Python; the
orchestration is declarative. The longer-term goal is for the LLM to
*author* new scripts from a natural-language scenario, making the bot
inherently extensible without touching the Python code.

The DSL keywords are English (`IF` / `ELSE`, `WHILE … LIMIT N`,
`FIND <tpl>.png`, `CLICK`, `CALL`, `WAIT`, `READ_TEXT`, …). The full,
current grammar is in [`dsl.md`](dsl.md) and the cheatsheet in
[`AGENTS.md`](../AGENTS.md) §4; the recognised vocabulary is centralised
in `script_engine.py` and easy to extend.

## Components

```
┌────────────────────────────────────────────────────────────────┐
│  INPUT: natural-language scenario / command / schedule         │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  PLANNER (LLMProvider)                                          │
│    Knows the skill catalogue. Decomposes the goal into a plan.  │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  EXECUTOR                                                       │
│    Loop: screenshot → classify → run_skill → verify → next.     │
│    Retry, fallback, screenshot dump on failure.                 │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  SKILLS  (Python — pre-built verbs)                             │
│    open_base, click_resource, find_template, wait_for_screen,   │
│    read_number, back, close_popup, ...                          │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  PERCEPTION                                                     │
│    template_match (OpenCV)    — fast lookups for known icons   │
│    OCR (RapidOCR / Paddle)    — numbers and labels             │
│    screen_classifier (VLM)    — "where are we?" (short reply)  │
│    VisionProvider fallback    — "I don't recognise this, help" │
└────────────────────────────────────────────────────────────────┘
                              ↓
┌────────────────────────────────────────────────────────────────┐
│  I/O ADAPTERS                                                   │
│    WindowCapture (Win32 / mss / windows-capture)                │
│    Input (pydirectinput / SendInput)                            │
└────────────────────────────────────────────────────────────────┘
```

## Model providers (pluggable)

Vision and text models are two independent extension points. The interfaces live in [`src/lastwar_bot/providers/base.py`](../src/lastwar_bot/providers/base.py):

- `LLMProvider.complete(LLMRequest) → str`
- `VisionProvider.describe(VisionRequest) → str`

Implementations:

| Provider         | Local / cloud      | Where it fits                                   |
|------------------|--------------------|-------------------------------------------------|
| `stub`           | neither            | dev mode with no external services; canned replies for pipeline testing |
| `ollama`         | local              | Qwen2-VL, Llama, Mistral, etc. through Ollama   |
| `openai_compat`  | cloud / self-host  | OpenAI, Anthropic-compat, Groq, Together, OpenRouter, llama.cpp server, vLLM |

Selection happens via the `LLM_PROVIDER` / `VISION_PROVIDER` env vars in `.env`. Adding a new provider = one file in `providers/` plus a branch in `providers/__init__._build`.

During development we use `stub` plus a **human-in-the-loop**: when a real semantic answer is needed (screen classification, screenshot review), the developer pastes the screenshot and the question to the assistant in chat, and the assistant's reply is applied as the VLM result. This lets us design skills and the executor before wiring in a real model.

## Hybrid perception

A VLM on a 2060 8 GB GPU costs seconds per call. So the hot path is CV+OCR (milliseconds), and the VLM is used:

1. for **screen classification** every N seconds (or when "we don't know where we are");
2. as a **fallback** when CV did not find the expected element;
3. in **dev mode** — to generate new templates and hints while building skills.

Over time the dataset grows and more navigation moves into the fast CV branch.

## Current status

The foundation is in place:

- ✅ Config (`config.py`), pydantic-settings + `.env`.
- ✅ Provider abstractions (`providers/base.py`).
- ✅ Implementations: `stub` (dev), Ollama (local), OpenAI-compat (cloud).
- ✅ Smoke test (`python -m lastwar_bot`).
- ✅ Window capture (`perception/capture.py`, GDI `PrintWindow`/`PW_RENDERFULLCONTENT`). CLI: `python -m lastwar_bot.perception.capture`.
- ✅ The window — the panel (`python -m panel`, or `panel.bat`), see `docs/panel-tabs.md`. The tick loop (`runner.py`) and Tk window (`ui.py`) that stood here were the first attempt at one; the panel replaced them and they have been deleted.
- ✅ Input layer (`inputs.py`):
  - **Foreground** via `pydirectinput` + `SetForegroundWindow` — verified end-to-end against a live Last War window (toggle button at client (1340, 970) → world screen, ~88 % of pixels changed).
  - **Background** via `PostMessage(WM_LBUTTONDOWN/UP)` — **not** supported by Last War; the game reads input through DirectInput / Raw Input and ignores window messages. Backend is kept in the module so we can probe other apps, but the bot must operate with the game window focused.
- ✅ Template matching (`perception/templates.py`): single-best `find()` and multi-instance `find_all()` with NMS deduplication. Useful when exact pixel-level templates are available at the current window size.
- ✅ Feature matching (`perception/features.py`):
  - **ORB + RANSAC** (`features.find`) for textured world objects (player bases, monsters, resource nodes).
  - **SIFT + RANSAC** (`features.SceneIndex.find_sift`) tuned for small UI icons (`contrastThreshold=0.02, edgeThreshold=20`). Crucially, **SIFT survives the game's UI re-rendering at different window sizes**, so a single template captured at the minimum supported window scales up to fullscreen. ORB extracts 0 keypoints on the same icons.
  - `SceneIndex` pre-computes SIFT features for the captured frame once so that probing it against many templates is cheap.
- ✅ Red attention-dot detector (`perception/red_dots.py`): HSV colour thresholding + contour shape filter. Default thresholds tuned against a live capture (`min_area=60, max_area=200, min_circularity=0.85`).
- ✅ Skill catalogue (`src/lastwar_bot/actions/*.md`) + DSL interpreter (`script_engine.py`). See [`dsl.md`](dsl.md) and [`farming.md`](farming.md) for what runs today.
- ✅ OCR provider — RapidOCR (`perception/ocr.py`, lazy-loaded), exposed as the `READ_TEXT` DSL primitive.
- ⏳ **Executor loop** as drawn above (screenshot → classify → run_skill → verify → next). The panel runs one action at a time; it can repeat a chosen one on an interval, and its Timers tab (`panel/timers.py`) keeps a configurable list of errands to their own clocks — the list is data and belongs to the profile (`panel/profiles/<name>/timers.json`: an action name or a sequence, a period, args; seeded from the template `panel/timers.json`), the clock is persisted beside it, and everything scheduled runs single-file on one worker thread. Nothing sequences a whole session yet.
- ⏳ **LLM-backed planner.** Never built — the bot acts through explicit `.md` recipes and Lua-VM routes, not an LLM-decomposed plan.
