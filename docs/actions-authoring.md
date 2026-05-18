# Authoring action scripts — a guide for LLMs and future sessions

This file is written for **the next agent (LLM or human) extending this
bot**. It assumes no prior context. Pair it with [`docs/dsl.md`](dsl.md)
(the formal DSL grammar) and [`docs/architecture.md`](architecture.md)
(the rest of the system).

## What the project is

A Windows desktop bot that automates the daily routine in *Last War —
Survival Game*. It captures the game window, identifies the current
screen, clicks on things. Detection is hybrid: SIFT feature matching
for tiny UI icons, template matching for pixel-exact lookups, ORB for
textured world objects, HSV colour rules for red attention dots. Input
is a real foreground click via `pydirectinput` (the game ignores window
messages).

## The architectural rule you must follow

The project deliberately splits into two layers:

```
src/lastwar_bot/actions/*.md     <- high-level skill scripts (game logic)
src/lastwar_bot/*.py             <- low-level primitives (no game knowledge)
```

When the user asks for a new behaviour, **default to writing or editing
a `.md` action script**. Touch Python *only* when:

- The DSL can't express what you need → add a new primitive
  (keyword + regex + interpreter case) and document it in `docs/dsl.md`.
- A primitive is broken → fix the runtime, not the script.
- Screen identification gains a new screen → extend
  `game/skills/navigate.py` (the one remaining game-aware Python module).

The ideal is that Python knows only *generic capabilities*: capture,
find, click, OCR, halt. Game-specific knowledge — which template, which
screen, which order — lives in scripts. Push that direction whenever
natural.

## Files you'll actually touch

```
src/lastwar_bot/
├── actions/                    *** SCRIPTS GO HERE ***
│   ├── go_to_base.md           # example: chrome-gated navigation
│   ├── go_to_world.md
│   ├── click_base_button.md    # leaf script: FIND + CLICK
│   ├── click_world_button.md
│   └── watchdog.md             # ticked every runner cycle
├── game/
│   ├── skills/navigate.py      # the one game-aware module (identify_screen)
│   └── templates/*.png         # PNG crops referenced by FIND
├── perception/
│   ├── capture.py              # window finding, screenshot, resize
│   ├── features.py             # SIFT (SceneIndex), ORB
│   ├── templates.py            # cv2.matchTemplate + NMS
│   └── red_dots.py             # HSV attention-dot detector
├── inputs.py                   # foreground/background click backends
├── runner.py                   # BotRunner: tick loop + watchdog dispatch
├── ui.py                       # Tk Debug UI
└── script_engine.py            # DSL parser + interpreter
```

## DSL recap (30-second version)

Full reference: [`docs/dsl.md`](dsl.md). Quick cheatsheet:

| Keyword | Form | Effect |
|---|---|---|
| `IF` / `ELSE` | `IF screen != base` … `ELSE` … | Branch on screen state or FOUND/NOT FOUND. |
| `FIND` | `FIND name.png` then indented block | SIFT-search for the template. Body runs only if matched. Sets implicit `LAST`. |
| `CLICK` | `CLICK` | Click the centre of `LAST`. Fails if no prior successful FIND. |
| `CALL` | `CALL action_name` | Run another `.md` script. Sub-failure propagates. |
| `WAIT` | `WAIT screen == base WITHIN 10s`<br>`WAIT 1.5` | Poll condition until true, or fixed sleep. |
| `LOG` | `LOG "msg"` | Trace line. |
| `STOP` | `STOP "reason"` | Halt the action stack; runner stops on the next check. |
| `CLOSE_WINDOW` | `CLOSE_WINDOW` | Send `WM_CLOSE` to the game window. |
| `CLICK (x, y)` | `CLICK (50, 50)` | Click absolute client coords (when FIND isn't usable, e.g. unique-per-player avatar). |
| `READ_TEXT (...)` | `READ_TEXT (300, 100, 400, 60) INTO profile.name` | OCR a region and save into the active profile. |
| `PRESS <key>` | `PRESS ESC` | Send a real keypress. Supports ESC/ENTER/SPACE/TAB/BACKSPACE/DELETE/HOME/END/PAGEUP/PAGEDOWN/UP/DOWN/LEFT/RIGHT, F1..F12, single letters/digits. |
| `WHILE <cond> [LIMIT N]` | `WHILE screen == unknown LIMIT 8` | Repeat body until condition is false or LIMIT hit. Default LIMIT = 20. |

Extended conditions:
- `FIND <tpl>.png` — ad-hoc SIFT find as a condition; updates `LAST`.
- `profile.<field> == "..."` / `profile.<field> != "..."` — string
  comparison against the active profile.

Conditions: `screen == base|world|unknown`, `screen != ...`,
`FOUND`, `NOT FOUND`. Comments start with `#`. Indentation can be any
consistent step (4 spaces is convention). Keywords are case-insensitive.

References:
- `<name>.png` always means a template in `src/lastwar_bot/game/templates/`.
- The operand of `CALL` always means another `.md` in
  `src/lastwar_bot/actions/`.

## Recipes (copy-paste patterns)

### One-liner that finds a button and clicks it
```
FIND inventory.png
    CLICK
```

### Chrome-gated navigation
```
# go_to_base.md
IF screen != base
    CALL click_base_button
    WAIT screen == base WITHIN 10s
```

### Reactive cleanup: a modal that may or may not be on screen
```
# close_alliance_modal.md
FIND alliance_close.png
    CLICK
    WAIT 0.5
```
(No `IF` needed — if the modal isn't there, FIND just skips its body.)

### Either/or fallback
```
# accept_or_skip.md
FIND accept_button.png
    CLICK
IF NOT FOUND
    LOG "no accept button; trying decline"
    FIND decline_button.png
        CLICK
```

### Watchdog with hard halt
```
# watchdog.md  (auto-run every runner tick)
FIND kicked_modal.png
    LOG "Another login detected"
    CLOSE_WINDOW
    STOP "kicked by another login"
```

### Composition
```
# daily_collect.md
CALL go_to_base
CALL collect_mail
CALL collect_resources
CALL go_to_world
CALL collect_world_truck
```

### Bounded recovery loop
```
# close_modals.md
WHILE screen == unknown LIMIT 8
    PRESS ESC
    WAIT 0.4
```
Press ESC until the bot can identify the current screen again — useful
as a first step in any flow that must start from a known state.

## Workflow: "the user just asked for behaviour X"

1. **Inspect**: read existing `actions/*.md` to see if you can compose
   them. Read `docs/dsl.md` for available primitives.
2. **Identify templates**: does the new behaviour need a new
   `game/templates/*.png`? If yes, request it from the user (they'll
   capture from the game) or describe what region to crop.
3. **Write the script**: smallest possible new `.md`. Compose via `CALL`
   if there's overlap.
4. **Add primitives only if forced**:
   - Update `script_engine.py`: add a `_*_RE` regex, an `_Stmt`
     dataclass, a parser branch in `_parse_one`, a `case` in
     `_run_stmt`, and a `_do_*` method.
   - Update `docs/dsl.md` (the user-facing grammar) and add the keyword
     to the table in this file.
5. **Smoke test**:
   - Parse: `python -X utf8 -c "from lastwar_bot import script_engine; print(script_engine.parse_file(script_engine.ACTIONS_DIR / 'NAME.md'))"`.
   - Run live: `from lastwar_bot.perception.capture import find_window; from lastwar_bot.script_engine import run_action; info = find_window('Last War-Survival Game', 'LastWar.exe'); print(run_action('NAME', info.hwnd, on_event=print))`.
   - Or via UI: launch `python -m lastwar_bot.ui` and use Debug tab.
6. **Commit**: a script-only change is *not* the same as a Python
   runtime change. Make that explicit in the commit message.

## When you must add a primitive — checklist

Indication: the user describes behaviour that needs a verb the DSL
doesn't have. Examples seen so far that *worked* with the existing set:
navigation, watchdog, modal cleanup. Examples that would require new
primitives:

- "Read the number on the energy counter" → needs `OCR <region>`.
- "Swipe up to scroll the alliance list" → needs `SWIPE <from> <to>`.
- "Wait until *any* of these icons appears" → needs `WAIT_ANY [a.png, b.png]`.
- "Press Escape" → needs `KEY <key>`.

For each, follow the **same recipe**:

```
script_engine.py:
  - Add `_FOO_RE = re.compile(r"^FOO ...$", re.IGNORECASE)`.
  - Add `@dataclass class FooStmt(_Stmt): ...`.
  - In `_parse_one`: `m = _FOO_RE.match(text); if m: return FooStmt(...)`.
  - In `_run_stmt`: `case FooStmt(): self._do_foo(stmt)`.
  - Add `def _do_foo(self, stmt): ...` that calls into the relevant
    Python primitive (e.g. `perception.ocr`, `inputs.swipe`, …).

docs/dsl.md:
  - Add a `### FOO ...` section under "Statements" with the form,
    semantics, and one example.
```

If the underlying Python capability doesn't exist either, that's two
PRs in one: add the primitive in `perception/` or `inputs.py` first,
then wrap it in DSL.

## Testing — what's available

- `script_engine.parse_file(path)` — parses and returns the AST, useful
  to verify syntax without running.
- `script_engine.run_action(name, hwnd, on_event=callback)` — executes
  end-to-end against a live game.
- Synthetic test pattern: write a temp `.md` under `actions/`, run, then
  delete. Used in commits to verify new primitives — example in the
  STOP test (`_test_halt.md` in `feat(actions): watchdog primitive`).
- UI Debug tab: live human-in-the-loop testing.
- Reference screenshots: `screenshots/before_input_test.png`,
  `screenshots/after_click.png`, `screenshots/world_zoom_out.png`,
  `screenshots/fullscreen.png`, `screenshots/true_fullscreen.png`,
  `screenshots/world_fs.png`. Use them for parser-only or
  template-cross-test runs without touching the live game.

## Pitfalls — don't repeat these mistakes

- **Game logic in Python**: every time you're about to add `if
  screen == 'base'` inside a Python function, ask if it belongs in a
  script. Almost always yes.
- **Pixel template matching as default for UI**: it breaks the moment
  the user resizes the window. Use SIFT (`features.SceneIndex.find_sift`)
  for UI icons; ORB for textured world objects; pixel templates only
  when you have multiple captures per resolution.
- **Tight crops without context**: SIFT needs a few keypoints. 40×40
  flat icons yield zero. The minimum useful template is ~60×60 with
  some surrounding pixels of contrast.
- **Mixing template references and action references in brackets**:
  the DSL is unambiguous — `.png` = template, no extension = action.
  Don't invent new bracket conventions.
- **Adding a keyword without updating `docs/dsl.md`**: an LLM
  reading the grammar reference would never produce a script using
  your new keyword. Always update both.
- **Letting Python know an icon name**: keep template filenames inside
  `.md` scripts; expose only the directory path from Python.
- **Russian inside repo artefacts**: chat may be Russian, files are
  English. Existing `docs/legacy-*/` is an archive of the old Lua
  project and stays Russian.

## Things the user appreciates

- One coherent commit per logical change. Script-only commits stay
  small and focused; Python-runtime commits explain *why* the DSL was
  insufficient.
- Detailed commit messages — they substitute for code comments and
  make it easy to recover context months later.
- Verifying with the live game when possible (you can call the
  Windows venv from WSL: `'.venv/Scripts/python.exe' -m lastwar_bot.…`).
  If the user is on the game, do the test and report the outcome
  rather than asking them to.
- Russian in chat. The user reads Russian replies; only files stay
  English.

## What's still incomplete (good extension points)

- **Numeric OCR primitive**: `READ_TEXT` lands a string in the profile.
  A `READ_NUMBER (region) INTO profile.<field>` variant that parses
  the OCR result as an integer would unlock typed comparisons
  (`profile.level >= "50"` instead of string equality).
- **Region-anchored find**: today `FIND` searches the whole image.
  A variant `FIND x.png NEAR LAST` (or `WITHIN <bbox>`) would speed
  up follow-up finds and reduce false positives in busy scenes.
- **Multi-instance find**: `templates.find_all` exists in Python but
  is not exposed in DSL. A `FIND_ALL x.png` returning a collection
  for iteration unlocks "click every truck on the world map".
- **Looping**: no `WHILE` / `FOR EACH` yet. Compose by repeating
  scripts for now; add when the first use case appears.
- **Calibration UI**: a Debug-tab button "Capture template here" that
  crops a region from the current screen and saves it. Today templates
  are produced ad-hoc with Python one-liners.
- **External AI primitive**: `ASK_VLM "<question>"` — sends the current
  capture to the configured `VisionProvider` (Ollama or OpenAI-compat)
  and binds the answer to a variable. For ambiguous screens.

When the user requests one of these, follow the "add a primitive"
checklist above.

## Glossary

- **action** — a single `.md` script under `actions/`. The filename
  without `.md` is its name (used by `CALL`).
- **template** — a `.png` under `game/templates/`. Always referenced
  with extension.
- **chrome** — the persistent right-column UI (mail, alliance, …).
  Used as a binary signal of "the game UI is visible".
- **LAST** — the implicit register holding the most recent successful
  `FIND` result. Consumed by `CLICK`.
- **runner** — `BotRunner` in `runner.py`. Manages the background
  tick loop; calls `watchdog.md` on every tick.
- **SIFT** — the feature-matching backend used for UI detection. Tuned
  in `features.default_sift()` (low contrast and edge thresholds so
  small icons get keypoints).
- **chrome-gate** — the navigation logic in `identify_screen`: if
  inventory matches, look for base/world toggles; otherwise look for
  the zoom-reset (max-world) toggle.
