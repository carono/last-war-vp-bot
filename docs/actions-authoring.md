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
├── actions/                    *** BLESSED SCRIPTS (tested, offered in the panel) ***
│   ├── donate_alliance_tech.md # the one verified end-to-end so far
│   └── dev/                    *** experimental / untested — still runnable ***
│       ├── go_to_base.md       # example: chrome-gated navigation
│       ├── click_base_button.md# leaf script: FIND + CLICK
│       ├── watchdog.md         # ticked every runner cycle
│       └── …                   # the rest of the vision actions
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

**Blessed vs. dev.** `actions/` holds only scripts verified to work end-to-end (right
now just `donate_alliance_tech.md`); everything else — the OCR/vision actions, the
watchdog — sits in `actions/dev/`. The panel's Scenarios list shows the blessed dir
only, so an operator can only run what's tested. Both are still runnable from code:
`resolve_action(name)` (used by `run_action` and the watchdog) looks in `actions/`
first, then `actions/dev/`, and `CALL` resolves across both. Promote a dev script by
moving it up into `actions/` once it is tested; the paths in the examples below refer
to files that now live under `actions/dev/`.

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
| `LAUNCH "path"` | `LAUNCH "C:\path\to\LastWarLauncher.exe"` | Start a detached process; pair with `WAIT screen == base` to block until the game is up. |
| `CLICK (x, y)` | `CLICK (50, 50)` | Click absolute client coords (when FIND isn't usable, e.g. unique-per-player avatar). |
| `READ_TEXT (...)` | `READ_TEXT (300, 100, 400, 60) INTO profile.name` | OCR a region and save into the active profile. |
| `PRESS <key>` | `PRESS ESC` | Send a real keypress. Supports ESC/ENTER/SPACE/TAB/BACKSPACE/DELETE/HOME/END/PAGEUP/PAGEDOWN/UP/DOWN/LEFT/RIGHT, F1..F12, single letters/digits. |
| `WHILE <cond> [LIMIT N]` | `WHILE screen == unknown LIMIT 8` | Repeat body until condition is false or LIMIT hit. Default LIMIT = 20. |
| `TAP <button> [xN\|xall]` | `TAP donate_1000 xall` | **Game-VM.** Press a named button N times, or `xall` = as many as its count allows (re-read until zero). The human-facing verb. |
| `LUA <chunk>` | `LUA UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)` | **Game-VM.** Authoring layer: run one raw in-engine call, verbatim. |
| `READ_LUA <expr> INTO <var>` | `READ_LUA ...:GetResDonateRestCount() INTO attempts` | **Game-VM.** Authoring layer: evaluate an expression into a script variable. |
| `<var> <op> <number>` | `WHILE attempts > 0 LIMIT 40` | Numeric condition on a READ_LUA variable. |
| `ARGS <name> = <default>` | `ARGS squads = [1, 2, 3]` | Declare a parameter. The caller's value wins; `{name}` is substituted into the script text before parsing, and the value is also a variable conditions can test. |
| `GAME WORLD` / `GAME CITY` | `GAME WORLD` | **Game-VM.** Single-call sugar: switch scene. |
| `JUMP x, y [, server]` | `JUMP 512, 640, 972` | **Game-VM.** Single-call sugar: coordinate jump. |

**Two backends, one grammar.** The vision primitives (FIND/CLICK/READ_TEXT/PRESS)
read the screen and click through a window handle; the **game primitives**
(TAP/LUA/READ_LUA/GAME/JUMP) drive the game through its own Lua VM (the warm daemon,
`tools/lua_daemon.py`) and need no handle. Mix them freely in one script. An action
made only of game primitives runs with `hwnd=0` — which is how the panel's
**Scenarios** tab runs it (pick a script, Run, or Repeat on an interval).

**You can edit a recipe from the panel.** The Scenarios tab opens the selected
script in an editor and saves it a second after you stop typing (Ctrl+Z undoes),
so the fix → run → read-the-log loop needs no other window. A run in flight locks
the list and marks its row; «Стоп» halts it at the next step.

**Parameters belong in `ARGS`, not in a copy of the script.** A recipe that
differs only by a number or a list takes an argument instead of being duplicated:
`join_rally.md` declares `ARGS squads = [1, 2, 3]` and is run as-is, from the
panel's «аргументы (JSON)» box (`{"squads": [2, 3]}`), or from a timer's `args`
block. `{squads}` is replaced in the text before parsing, so an argument can land
anywhere — including inside a `LUA` chunk.

**Recipes read like button presses; engine names hide in the catalogue.** The
everyday form is `TAP <button>` — see `donate_alliance_tech.md`, which is a single
`TAP` line. The ugly `UIManager.Instance:OpenWindow(...)` calls live once in
`tools/lib/game_buttons.py` (`name -> {lua, wait, label}`); a recipe author adds a
button there and then just `TAP`s it. `LUA`/`READ_LUA` are the authoring layer for
defining buttons or a bespoke count-gated loop (spend *exactly* N attempts). Two hard
rules: don't bury a whole multi-step flow in one opaque keyword, and **never**
loop-and-wait-on-server inside one `LUA` chunk (it freezes the client — loop with
`TAP xN` or `WHILE`+`WAIT`, each of which pauses between calls). See
[`docs/dsl.md`](dsl.md#game-primitives-lua-vm-no-pixels).

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

> **Behaviour the game already has a button for?** Don't guess the engine
> calls — record the player doing it once and reverse it. Recording a session
> is [`docs/skills/sniff-capture.md`](skills/sniff-capture.md); turning the
> recorded trace + wire into `game_buttons.py` → this `.md` is the strict
> checklist [`docs/skills/sniff.md` §8.0](skills/sniff.md#80-the-strict-checklist--analysis-in-10-minutes).
> The steps below pick up from there, at "write the script".

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
- **Dynamic centres**: if the only stable part of a UI element is its
  outer frame (centre shows a changing number / portrait / progress),
  capture the template as a regular PNG, then erase the dynamic centre
  to transparent in an image editor. The runtime treats `alpha < 128`
  pixels as "don't extract keypoints here", so only the stable outline
  contributes to the match.
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
