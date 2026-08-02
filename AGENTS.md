# Agent handover — Last War Bot

**Read this file first if you're a new LLM session, a returning one, or a
human contributor coming into the project after a break.** It is the
canonical entry point. Everything in `docs/` is detail; this file is
orientation, the architectural rules, and the hard-won lessons you must
not re-learn the hard way.

---

## 1. What this project is

A Windows desktop bot that automates the daily routine in *Last War —
Survival Game*. The game has an official PC client (DirectX); the bot
captures its window, identifies the current screen, clicks on things,
OCRs the things it needs to know, runs on a tick loop with a watchdog.

It replaces a legacy Lua / UOPilot project (`master` branch, kept as
read-only reference). The current branch is `v2`.

User profile / context (from project memory):
- The user plays on their own home server.
- Chat language: **Russian**. Repo artefacts (code, docs, YAML, commit
  messages): **English**. The archived `docs/legacy-*/` folders stay
  Russian — they're an archive, not a living document.
- Multi-operator: different people will run their own copies, each with
  their own profile id (`--profile <id>`). Per-machine paths use
  environment variables (`%LOCALAPPDATA%`).

---

## 2. The architectural rule — **actions-first**

Behaviour is split into two strict layers:

```
src/lastwar_bot/actions/*.md     <- HIGH-LEVEL skill scripts (game logic)
src/lastwar_bot/*.py             <- LOW-LEVEL primitives (no game knowledge)
```

When the user asks for new behaviour, **default to writing or editing a
`.md` action script**. Touch Python **only** when:

- the DSL can't express what you need — add a primitive and document it
  in `docs/dsl.md`;
- an existing primitive is broken — fix the runtime, not the script;
- a new screen needs identifying — extend `game/skills/navigate.py`,
  the one remaining game-aware Python module.

Ideal end state: Python knows only generic capabilities (capture, find,
click, OCR, halt, launch). Game-specific knowledge — which template,
which screen, which order — lives in scripts. Push toward that whenever
natural. The user has explicitly endorsed this rule and will eventually
have an LLM author scripts from natural-language scenarios.

The same rule governs the control panel, which grew after this section
was written: **the panel is a player of scenarios, not a bot.** A button
runs `script_engine.run_action(<name>, …)`; no game logic, no Lua, no
gates and no step sequences live under `panel/`. The binding wording,
including what to do with the panel code that predates the rule, is in
[`CLAUDE.md`](CLAUDE.md) — read it before touching either layer.

---

## 3. File map

```
AGENTS.md                              <- you are here
README.md                              user-facing intro (RU mirror: README.ru.md)
run.bat                                Windows launcher (forwards %*)
requirements.txt                       pip dependencies
pyproject.toml                         setuptools package

src/lastwar_bot/
├── __main__.py                        smoke test (python -m lastwar_bot)
├── ui.py                              Tk control window (python -m lastwar_bot.ui)
├── ui_region.py                       region-picker Toplevel for calibration
├── runner.py                          background tick loop + watchdog dispatch
├── script_engine.py                   DSL parser + interpreter
├── inputs.py                          click / press_key (Win32 native)
├── config.py                          pydantic-settings, .env-driven
├── profile.py                         per-player JSON profile under ./profiles/
├── providers/                         LLM / VLM abstraction
│   ├── base.py                          LLMProvider / VisionProvider interfaces
│   ├── stub.py                          dev-mode canned responses
│   ├── ollama.py                        local
│   └── openai_compat.py                 cloud or self-host
├── perception/                        vision / input primitives (no game logic)
│   ├── capture.py                       window discovery + screenshot + resize
│   ├── templates.py                     cv2.matchTemplate single + multi (NMS)
│   ├── features.py                      ORB and SIFT + SceneIndex
│   ├── ocr.py                           RapidOCR wrapper
│   └── red_dots.py                      HSV attention-dot detector
├── game/
│   ├── skills/navigate.py             ONLY game-aware Python: identify_screen
│   └── templates/*.png                  reference images (FIND targets)
└── actions/*.md                       DSL scripts (skill catalogue)

docs/
├── architecture.md                    system design + state
├── dsl.md                             formal DSL grammar (user-facing)
├── actions-authoring.md               deep dive for script authors / LLMs
├── install/                           Windows install guides
├── game/                              game knowledge (overview, daily cycle, glossary, screens)
└── legacy-{en,ru}/                    archived old project, read-only reference

profiles/                              gitignored — per-player JSON
screenshots/                           gitignored — runtime captures, debugging dumps
```

---

## 4. Current capabilities — quick inventory

### DSL primitives (`script_engine.py`)

| Keyword | Form | Notes |
|---|---|---|
| `IF` / `ELSE` | `IF screen != base` | branches; ELSE optional |
| `WHILE … LIMIT N` | `WHILE screen == unknown LIMIT 8` | bounded loop, default LIMIT=20 |
| `FIND <tpl>.png` | as statement or as condition | statement: indented body runs if found; condition: ad-hoc match that updates `LAST` |
| `CLICK` | `CLICK` / `CLICK (x, y)` | bare = `LAST`'s centre; with coords = absolute client px |
| `PRESS <key>` | `PRESS ESC` | ESC/ENTER/SPACE/TAB/BACKSPACE/DELETE/HOME/END/PAGEUP/PAGEDOWN/UP/DOWN/LEFT/RIGHT/F1..F12/letters/digits |
| `CALL <action>` | `CALL go_to_base` | run another `.md`; failure propagates |
| `WAIT cond [WITHIN N s]` | `WAIT screen == base WITHIN 10s` | poll until condition true or timeout |
| `WAIT N` | `WAIT 1.5` | plain sleep (seconds) |
| `READ_TEXT (x, y, w, h) INTO profile.<f>` | OCR a region, save to active profile (auto-persists) |
| `LOG "msg"` | trace line |
| `STOP ["reason"]` | halt the whole action chain; runner stops on next check |
| `CLOSE_WINDOW` | send WM_CLOSE to the game window |
| `LAUNCH "path"` | spawn a detached process; `%VAR%` / `$VAR` / `~` are expanded |
| `SCAN_SECRET_MISSIONS [LEVEL n] [STAR] [CAN_LOOT] [FREE_SLOTS n] [WITHIN N s]` | secret tasks read off the **wire**, not the screen; fills `MISSIONS` |

Conditions allowed in `IF` / `WHILE` / `WAIT`:
- `screen == base|world|unknown`, `screen != …`
- `FOUND` / `NOT FOUND` (state of the last FIND **statement**)
- `FIND <tpl>.png` (ad-hoc; also updates `LAST` on success)
- `profile.<field> == "text"` / `profile.<field> != "text"`
- `missions.count ==|!=|>|<|>=|<= N` (result of the last SCAN_SECRET_MISSIONS)

### Action scripts (`actions/`)

Existing skills the user maintains:
- `launch_game.md` — start the launcher, wait up to 5 min for base.
- `go_to_base.md`, `go_to_world.md` — chrome-gated navigation.
- `click_base_button.md`, `click_world_button.md` — leaf find+click.
- `close_modals.md` — press ESC until the screen is recognised again.
- `close_profile_modal.md` — close the profile dialog by template.
- `capture_profile.md` — OCR player name / level / server into profile JSON.
- `scan_secret_missions.md` — find raidable secret tasks by level / loot
  slots, reading the game's own map traffic instead of the screen.
- `watchdog.md` — runs every runner tick; reacts to the "logged in from
  another device" modal (template `kicked_modal.png`) by closing the
  game and halting the bot.

### Perception primitives (`perception/`)

- `capture.py`:
  - `find_window(title_substring, process_name)` — returns `WindowInfo`.
  - `grab(hwnd)` — BGR `ndarray`, **client-area only** (uses
    `PW_CLIENTONLY | PW_RENDERFULLCONTENT`).
  - `ensure_client_size(hwnd, …)` — grows window if below
    `MIN_CLIENT_WIDTH × MIN_CLIENT_HEIGHT` (1638×1026 / target 1700×1080).
- `features.py`:
  - `SceneIndex(image).find_sift(template_path)` — SIFT + RANSAC
    affine-partial fit. PNGs with an alpha channel use alpha as a
    keypoint mask (centre of a frame can be transparent and ignored).
  - `find(image, template)` — ORB+RANSAC. For textured world objects,
    not flat UI icons (ORB extracts 0 keypoints from 64x64 buttons).
- `templates.py`:
  - `find(image, template, threshold=0.85)` — single best matchTemplate.
  - `find_all(image, template, …)` — multi-instance with NMS.
- `ocr.py`:
  - `read_text(image, region=None)` — RapidOCR, lazy-loaded.
- `red_dots.py`:
  - `find_red_dots(image, …)` — HSV + circular contour filter; defaults
    `min_area=60, max_area=200, min_circularity=0.85`.

### Input primitives (`inputs.py`)

- `click(hwnd, x, y, mode="foreground"|"background")` —
  foreground uses `SetCursorPos + mouse_event` (raw screen pixels,
  multi-monitor + negative coords work); background uses `PostMessage`
  but **Last War ignores it** (DirectInput).
- `press_key(hwnd, key_name)` — `keybd_event`, foreground.

### UI (`ui.py`)

`python -m lastwar_bot.ui --profile <id>`  (or `run.bat --profile <id>`)

- Header: status + provider names + profile id.
- Main tab: Start / Stop / Clear log.
- Debug tab:
  - **Detect** — show current screen.
  - **Go to Base / Go to World** — run `go_to_base.md` / `go_to_world.md`.
  - **Fix window size** — call `ensure_client_size`.
  - **Capture profile** — run `capture_profile.md`.
  - **Pick region…** — opens a Toplevel with the live capture; drag a
    rectangle, get `(x, y, w, h)` to clipboard or save the crop as PNG.
  - **Launch game** — run `launch_game.md`.
- Log: read-only, supports selection, Ctrl+C / Ctrl+A, right-click menu
  with Copy / Select all / Clear.

### Providers

- `stub` (default, dev): canned responses. Use this until real AI is
  needed.
- `ollama`: local LLM / VLM. Daemon at `http://127.0.0.1:11434`.
- `openai_compat`: any OpenAI-compatible API (OpenAI, Anthropic /v1,
  Groq, Together, OpenRouter, local llama.cpp/vLLM).

Switched via env vars in `.env`:
```
LLM_PROVIDER=stub|ollama|openai_compat
VISION_PROVIDER=stub|ollama|openai_compat
```

---

## 5. Hard-won lessons — do not re-learn

Each is hours of debugging that's now locked in code or templates.

### Multi-monitor + pydirectinput → clicks drift on negative-X monitors
`pydirectinput.moveTo` normalises to 0-65535 relative to the primary
monitor. On a secondary monitor at negative screen-x the cursor lands
tens of pixels off. **Fix**: use `win32api.SetCursorPos` (raw screen
pixels, full virtual desktop). Currently in `inputs._click_foreground`.

### PrintWindow without PW_CLIENTONLY → captures include the title bar
With just `PW_RENDERFULLCONTENT` the bitmap is window-sized starting at
window top-left; the first ~30 rows are the OS title bar and the rest
is shifted down. Combined with the above, made clicks ~50 px low.
**Fix**: `PrintWindow(hwnd, dc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)`
— flag `3`. Currently in `perception.capture.grab`.

### `cv2.findHomography` overfits on tiny templates
On 33×33 icons with ~8 inliers, the 8-parameter projective fit
hallucinates wild stretches and shifts the projected centre. **Fix**:
`cv2.estimateAffinePartial2D` (4 parameters: translation + uniform
scale + rotation). Currently in `features.SceneIndex.find_sift`.

### SIFT defaults find zero keypoints on small flat UI icons
`contrastThreshold=0.04, edgeThreshold=10` are too strict for 60×40
shaded buttons. **Fix**: `cv2.SIFT_create(nfeatures=5000,
contrastThreshold=0.02, edgeThreshold=20)`. Currently in
`features.default_sift()`.

### ORB extracts 0 keypoints from clean UI icons
ORB needs corners. Use **SIFT** for UI (`features.SceneIndex.find_sift`)
and ORB only for textured world objects (`features.find`).

### Multi-resolution: the game re-renders icons per window size
A pixel-template captured at one window size won't match at another —
the game produces a different rasterisation, not a scaled copy. Even
multi-scale `matchTemplate` tops out at score ~0.80 (under the 0.85
threshold). **Fix**: switched to SIFT for UI; SIFT survives the
re-rasterisation. For pixel-templates (rarely used now) keep a variant
per `(window-size × screen)` combo.

### Chrome-gate detection
Some toggle icons look identical between states (map+pin appears on
both Base and on max-zoom World). Disambiguate by gating on the
right-column UI (`inventory.png`): chrome present ⇒ base/world by
toggle; chrome absent ⇒ either world-far or some loading state.
Currently in `navigate.identify_screen`.

### Last War ignores message-based input
`PostMessage(WM_LBUTTONDOWN/UP)` and `WM_KEYDOWN/UP` are dropped by
Last War's DirectInput path. The bot **must** run with the game window
focused. Background input is kept in the codebase for probing other
apps. (Memory: `project-input-model`.)

### Cross-session control is not possible
A bot in user session A can't see windows owned by user session B
(EnumWindows is per-session). RDP / fast-user-switching: the bot and
the game must run in the same user session.

### Internal SIFT FIND retry papers over RANSAC stochasticity
A single SIFT attempt occasionally fails right at the 4-inlier floor.
`script_engine._do_find` retries up to 3 times with 200 ms delays —
transparent to the script, eliminates flake.

### Click landing precision — chain of correctness
For a click to land on a SIFT match the *whole* pipeline must be right:
PrintWindow with PW_CLIENTONLY → SIFT affine-partial → ClientToScreen →
SetCursorPos. If a click is missing by tens of pixels, suspect (in
order): (1) capture flag, (2) homography model, (3) pydirectinput vs
SetCursorPos.

---

## 6. Workflow recipes

### "Add behaviour X"
1. Read `docs/dsl.md` and existing `actions/*.md`. Try to compose.
2. Need new templates? Use UI → Debug → **Pick region…** and save under
   `game/templates/`. For frames around dynamic content, erase the
   centre to transparent (alpha < 128 = mask).
3. Need new OCR regions? Same picker — **Copy coords** gives
   `(x, y, w, h)` ready to paste into a `READ_TEXT` line.
4. Compose / extend `.md` files. Commit "script-only" with that wording.

### "DSL can't express X" (you need a primitive)
1. Decide the keyword form (1-line statement vs compound with body).
2. In `script_engine.py`: add a regex, a dataclass `XxxStmt`, a branch
   in `_parse_one`, a `case` in `_run_stmt`, and a `_do_xxx` method.
3. If a low-level capability is missing too, add it under
   `perception/` or `inputs.py` first, then wrap in DSL.
4. Update `docs/dsl.md` and the cheatsheet in this file (section 4).
5. Validate by parsing (`parse_file`) and via a synthetic temp `.md`.

### "Click misses target" diagnosis order
1. Save the SIFT match's bounding box on the captured frame — does the
   box land on the icon? If not, it's a SIFT / homography problem.
2. Compare what `ClientToScreen(hwnd, (cx, cy))` returns with
   `win32api.GetCursorPos()` after the move — if they differ, it's an
   input-routing problem.
3. Check the top rows of `grab(hwnd)` — if you see the OS title bar,
   PW_CLIENTONLY isn't applied.

### Adding a new screen to `identify_screen`
1. Capture a screenshot showing the new screen at a known good size.
2. Cut a stable distinguishing element (via Pick region) into
   `game/templates/`.
3. Add a branch in `navigate.identify_screen` returning the new name.
4. Update conditions: any `screen == <name>` references in scripts
   need to be valid (currently we only have `base` / `world` /
   `unknown`).

---

## 7. Project memory (~/.claude/.../memory/)

Three feedback/project facts already stored across sessions:

- **feedback-repo-language** — English in repo artefacts, Russian in
  chat. Legacy folders stay Russian.
- **project-input-model** — foreground input only; PostMessage is
  ignored; bot must keep the game focused.
- **feedback-actions-first** — new behaviours go in `actions/*.md`;
  Python only when a primitive is missing.

A returning session loads these automatically — they take precedence
over guesswork.

---

## 8. Conventions

- **Indentation in scripts**: any consistent step works (parser is
  flexible); convention is 4 spaces.
- **Commit messages**: state whether the change is to a *script*, the
  *runtime*, or the underlying *primitive*. Detailed bodies — they're
  the project's narrative.
- **Don't `--no-verify`** on commits, don't `--force` push, don't
  amend published commits.
- **One coherent change per commit**. Script-only commits stay tiny;
  Python commits explain *why* the DSL was insufficient.
- **Never put a username into a path** — use `%LOCALAPPDATA%`,
  `%USERPROFILE%`, etc. `LAUNCH` paths expand them automatically.

---

## 9. Open extension points

Whenever the user requests one of these, follow the "add a primitive"
recipe in section 6.

- **Region-anchored FIND** — `FIND x.png NEAR LAST` / `WITHIN (bbox)`
  to speed up follow-ups and avoid false positives in busy scenes.
- **FIND_ALL in DSL** — `templates.find_all` exists in Python but isn't
  exposed; unblocks "click every truck on the map".
- **Typed OCR** — `READ_NUMBER (region) INTO profile.<f>` that parses
  the OCR text as an integer; today's `READ_TEXT` stores strings,
  comparisons are string-only.
- **Calibration UI for templates** — Pick region is the starting
  point; could be extended with a "Save with alpha-masked centre"
  flow that asks for an inner rectangle to erase.
- **VLM ASK primitive** — `ASK_VLM "question" INTO profile.x` that
  sends the current capture to the configured `VisionProvider` and
  binds the answer. Needed when ambiguous screens require a smarter
  fallback than templates.
- **Loops by iteration**: `FOR EACH match IN FIND_ALL …` (depends on
  FIND_ALL).

---

## 10. Pointers — where to dig deeper

- **`docs/architecture.md`** — system design with component diagram.
- **`docs/dsl.md`** — formal grammar (user-facing reference).
- **`docs/actions-authoring.md`** — deep-dive recipes and primitive-
  authoring checklist.
- **`docs/game/`** — game knowledge: overview, daily cycle, glossary,
  per-screen notes.
- **`docs/install/`** — Windows install for a new operator.
- **`docs/research/panel-tabs-refactor.md`** — the migration plan for the
  control panel: every tab a self-contained runnable module, the panel a
  shell that plugs them in. Read it before touching `panel/__main__.py`.

---

## 11. Status

Everything in section 4 works. The bot can:

- launch the game, wait for the base screen;
- navigate between base and world via SIFT-found toggle clicks;
- detect & dismiss the "kicked by another login" modal via the watchdog;
- press ESC to close stacked popups until the screen is recognised;
- capture player profile (name / level / server) via OCR into a JSON
  profile; switch profiles via `--profile`;
- crop new templates and copy OCR-region coords from a live capture
  without leaving the UI.

What hasn't been built yet — the **daily activity sequence**
(see `docs/game/daily_cycle.md`): mail, radar, secret missions, base
resources, alliance donations + gifts, events / Arms Race / VS,
monster rallies. These will become `.md` scripts (composing existing
primitives and any newly added ones such as FIND_ALL, READ_NUMBER,
SWIPE). When the user asks for one of those flows, start by reading
`docs/game/daily_cycle.md` for the order and any timing constraints.

Good luck — and when in doubt, **default to a script change**.
