# Architecture (v2)

## Separation of concerns

The main pain point of v1 (Lua/UOPilot) was pixel-colour navigation: any UI update broke the scripts. v2 splits the problem into two layers:

- **Python — "hands and eyes".** Window capture, template matching (OpenCV), OCR, mouse/keyboard input, state verification, retry/recovery. These primitives are predictable, fast (milliseconds), and deterministic.
- **AI — "semantic glue".** When we need to understand "what's on the screen right now", or to decompose a high-level goal ("collect resources at the base") into a sequence of known-good actions, we ask a VLM/LLM. The AI is called sparingly, on demand, not on every tick.

Top-level flow: `"collect resources at the base"` → **planner** turns it into `[open_base, find_resource_icons, click_each, return]` → **executor** runs each step through pre-built Python skills → after each step it compares the expected screen with the actual one (via the classifier) → on mismatch, it triggers recovery.

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
- ✅ Bot runner (`runner.py`) — background-thread loop with thread-safe start/stop/restart. Current tick captures one frame and reports stats; real activities will plug in later.
- ✅ Tk control UI (`ui.py`) — Start / Stop / Clear log, status indicator, live log. Launch: `python -m lastwar_bot.ui`.
- ⏳ Input layer (pydirectinput foreground + PostMessage background test).
- ⏳ Skill catalogue and executor.
- ⏳ LLM-backed planner.
- ⏳ OCR provider (RapidOCR vs PaddleOCR decision after the first real run).
