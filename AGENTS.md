# Agent handover — Last War Bot

**Read this file first if you're a new LLM session, a returning one, or a
human contributor coming into the project after a break.** It is the
canonical entry point. Everything in `docs/` is detail; this file is
orientation, the architectural rules, and the hard-won lessons you must
not re-learn the hard way.

---

## 1. What this project is

A Windows desktop bot that automates the daily routine in *Last War —
Survival Game*. The game has an official PC client (DirectX). Most of what
the bot does now goes through the client's own Lua VM — headless, no window
raised, no pixels read — and the CV/OCR half (capture the window, identify
the screen, click, OCR) is used where no Lua route exists. What runs when is
the panel's business: a schedule of errands, each of them a scenario.

It replaces a legacy Lua / UOPilot project, which is now history rather
than a branch: commit `b5ce084` is the last tip that carried its tree, and
it stays there as read-only reference. **Work happens on `master`.** The
rewrite grew up on `v2`; that branch has been merged into `master` and left
at the merge point for the checkouts that still track it. Nothing is
committed to it any more, and it will fall behind — do not push there and do
not branch off it.

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
CLAUDE.md                              the binding rules (actions-first, tabs, i18n, …)
README.md                              user-facing intro (RU mirror: README.ru.md)
install.bat                            one-shot install + desktop shortcuts
panel.bat                              start the panel (forwards %*, e.g. --profile alice)
daemon.bat                             start the warm Lua daemon by hand
update.bat                             pull and re-install
requirements.txt                       pip dependencies (requirements-tools.txt: the sniffers)
pyproject.toml                         setuptools package

panel/                                 THE WINDOW — and the only interface there is
├── __main__.py                          the shell: window, notebook, log, menu, «Главная»
├── runtime/                             what a tab talks to: the game link, the claim,
│                                        the schedule, settings, children, i18n, …
├── tabs/                                one plugin per tab (docs/panel-tabs.md)
├── web/                                 the same runtime, drawn for a phone (#1221)
├── locales/                             eleven JSON files — every string the panel says
└── profiles/                            gitignored — per-profile config, logs, state

tools/                                 command-line tools; `tools/lib/` is the shared half
├── lua_daemon.py                        one warm LuaEval per client, on its own port
├── lib/lua_client.py                    how everything talks to that daemon
├── lib/game_paths.py                    where the game is — every per-machine answer
├── lib/lua_actions.py                   the Lua chunks a primitive sends
└── lib/game_buttons.py                  the button catalogue `TAP` presses

tests/                                 self-running scripts (no pytest — see §8)

src/lastwar_bot/
├── __main__.py                        smoke test (python -m lastwar_bot)
├── ui_region.py                       region-picker Toplevel for calibration
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
├── farming.md                         WHAT THE BOT CAN DO — the feature list (RU: farming.ru.md)
├── panel-tabs.md                      how to write a panel tab; read before writing one
├── architecture.md                    the original v2 design + what became of it
├── dsl.md                             formal DSL grammar (user-facing)
├── actions-authoring.md               deep dive for script authors / LLMs
├── game-glossary.md                   the game's own words, in all eleven languages
├── install/                           Windows install guides
├── game/                              game knowledge (overview, daily cycle, glossary, screens)
├── skills/                            how to record and read a sniffer session
├── research/                          one file per ability: protocol, Lua route, findings
└── legacy-{en,ru}/                    archived old project, read-only reference

profiles/                              gitignored — per-player JSON (the bot's own, not the panel's)
results/                               gitignored — captures, traces, tool output
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
| `ARGS <name> = <default>` | `ARGS level = 30` | declare an input; the caller passes `variables={"level": …}`, `$name` interpolates |
| `LOG "msg"` | trace line |
| `FAIL ["reason"]` | `FAIL "no squad free"` | end the scenario UNsuccessfully, in its own words; the panel shows the reason |
| `STOP ["reason"]` | halt the whole action chain and leave the flag on the context |
| `CLOSE_WINDOW` | send WM_CLOSE to the game window |
| `LAUNCH "path"` | spawn a detached process; `%VAR%` / `$VAR` / `~` are expanded |
| `START_GAME ["path"] [WITHIN N s]` | start the game client **where this profile's client lives** — this desktop, or the Windows session the profile names, through `tools/session_launch.py` |
| `QUIT_GAME` | force-close the client this profile drives (the pid its daemon holds), and wait for it to go |
| `ATTACH_GAME [WITHIN N s]` | re-point the warm Lua daemon at the client running now — the other half of a restart |
| `SCAN_SECRET_MISSIONS [LEVEL n] [STAR] [CAN_LOOT] [FREE_SLOTS n] [WITHIN N s]` | secret tasks read off the **wire**, not the screen; fills `MISSIONS` |

**Through the game's own Lua VM — no window raised, no pixels read.** This is the
half most scenarios are written in now; the CV primitives above are for what has no
Lua route. Full grammar in [`docs/dsl.md`](docs/dsl.md) §Game primitives.

| Keyword | Form | Notes |
|---|---|---|
| `TAP <button> [xN \| xall]` | `TAP heal_all xall` | press one named button from the catalogue (`tools/lib/game_buttons.py`); `xall` re-reads the button's own count and spends what is there |
| `LUA <chunk>` | `LUA SceneUtils.ChangeToCity()` | run one chunk in the VM, verbatim; errors surface as a log line |
| `READ_LUA <expr> INTO <var>` | `READ_LUA … INTO wounded` | evaluate an expression and keep the value for `IF` / `WHILE` |
| `GAME WORLD` / `GAME CITY` | switch scene through the VM (not a click) |
| `JUMP x, y [, server]` | `JUMP 512, 480, 1226` | walk the camera to a tile, same or cross-server |

Conditions allowed in `IF` / `WHILE` / `WAIT`:
- `scene == city|world|unknown`, `scene != …` — **the state one**, asked of the Lua
  VM: `city` means the base is in play with its HUD up. Prefer it to `screen`.
- `screen == base|world|unknown`, `screen != …` — the pixel one (SIFT).
- `<var> ==|!=|>|<|>=|<= <number>` — a value `READ_LUA … INTO <var>` or `ARGS` put there
- `FOUND` / `NOT FOUND` (state of the last FIND **statement**)
- `FIND <tpl>.png` (ad-hoc; also updates `LAST` on success)
- `profile.<field> == "text"` / `profile.<field> != "text"`
- `missions.count ==|!=|>|<|>=|<= N` (result of the last SCAN_SECRET_MISSIONS)

### Action scripts (`actions/`)

**`actions/` is blessed, `actions/dev/` is not.** The panel offers the blessed
directory only; both are runnable from code, and `CALL` resolves across the two.
The list below is a shape, not an inventory — the directory is the inventory, and
what each ability does for the PLAYER is [`docs/farming.md`](docs/farming.md).

- **The client's own life** — `launch_game.md` (start it *in the Windows session
  this profile's client lives in*), `quit_game.md`, `restart_game.md`,
  `recover_from_kick.md`, `switch_account.md`.
- **The base** — `collect_base_resources.md`, `collect_truck_resources.md`,
  `collect_visitor_gifts.md`, `recruit_survivors.md`, `heal_units.md`,
  `upgrade_decorations.md`.
- **The alliance** — `donate_alliance_tech.md`, `collect_alliance_gifts.md`,
  `help_ally.md`, `apply_ministry_interior.md`, `submit_ministry.md`.
- **The map** — `steal_secret_task.md`, `steal_ghost_recon.md`,
  `create_rally.md`, `join_rally.md`, `rally_monitor.md`, `occupation_skills.md`.
- **Readings and settings** — `read_squad_state.md`, `read_graphics_load.md`,
  `set_graphics_load.md`, `send_chat_message.md`.
- **`actions/dev/`** — the older pixel-driven ones (`go_to_base.md`,
  `close_modals.md`, `capture_profile.md`, `scan_secret_missions.md`,
  `watchdog.md`, …). They still run; nothing ticks `watchdog.md` by itself.

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

### The window

There is one, and it is the panel: `panel.bat`, or `python -m panel`
(`docs/panel-tabs.md`). The Tk window this package used to carry —
`ui.py`, its `runner.py` tick loop and the `run.bat` that started them
through a `.venv` — is gone: it had been replaced by the panel long
before it was deleted, and nothing had imported it for as long.

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

### Cross-session control needs a helper in the other session — but it works
A process in Windows session A cannot see or click a window of session B
(`EnumWindows` is per-session), and the anti-cheat kills a client started under a
foreign token. That used to read as "impossible", and it is why a second account
runs the way it does (`docs/research/multi-instance-rdp.md`, #1106/#1218):

- the second client lives in **its own Windows session**, logged on as its own
  account, started there by `tools/session_launch.py` under that session's own
  token — never spawned from this desktop;
- a **daemon of its own** (`tools/lua_daemon.py`, its own port) runs INSIDE that
  session beside it, and everything this side does travels over that port;
- so the panel drives it headlessly through Lua, and never through a window.

What still holds: nothing pixel-driven reaches across, one client per session,
and a daemon started on the wrong desktop binds the right port and drives the
wrong game — which is exactly how #1224 went unnoticed for two days.

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
2. **Look for a Lua route before a pixel one.** Almost everything the bot does
   now is `TAP` / `LUA` / `READ_LUA` — headless, no window raised, no template to
   maintain. `docs/research/` has one file per ability that was found that way,
   and `tools/lib/game_buttons.py` is the catalogue `TAP` presses.
3. Only if there is no Lua route: crop a template into `game/templates/` (name it
   from the table in that folder's README) and read a `READ_TEXT` rectangle off a
   screenshot of the client. For frames around dynamic content, erase the centre
   to transparent (alpha < 128 = mask). `ui_region.py` holds a picker widget for
   this, but nothing opens it any more — the window that did is gone.
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
2. Cut a stable distinguishing element out of it into `game/templates/`.
3. Add a branch in `navigate.identify_screen` returning the new name.
4. Update conditions: any `screen == <name>` references in scripts
   need to be valid (currently we only have `base` / `world` /
   `unknown`).

---

## 7. Project memory (~/.claude/.../memory/)

Dozens of facts are stored across sessions and indexed in `MEMORY.md` — how the
Lua route into the game was found, what a second account needs, which readings
are gated, which diagnoses cost a day. The ones that govern how you WORK here:

- **feedback-repo-language** — English in repo artefacts, Russian in
  chat. Legacy folders stay Russian.
- **feedback-actions-first** — new behaviours go in `actions/*.md`;
  Python only when a primitive is missing.
- **project-input-model** — foreground input only; PostMessage is
  ignored; anything pixel-driven needs the game focused.
- **feedback-never-git-add-all / stage-only-my-lines** — the working tree is
  shared with other agents. Stage your own paths, never `-A`, and verify a
  commit by reading its content back.

A returning session loads these automatically — they take precedence
over guesswork, but they are notes from a moment: if one names a file or a
flag, check it still exists before acting on it.

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
- **Never put an INSTALL into a path either.** Where the game is, is
  `tools/lib/game_paths.py` and nothing else — one resolver, read by the
  panel, the tools and the DSL alike, every value an environment
  variable with the old literal as its default:

  | variable | default | what it is |
  |---|---|---|
  | `LW_LAUNCHER` | *(built from the two below)* | the launcher — an override for an install that is not ordinary |
  | `LW_GAME_DIR` | `%LOCALAPPDATA%\FunFly\Last War-Survival Game` | the install folder |
  | `LW_GAME_FOLDER` | `FunFly\Last War-Survival Game` | the same, *relative to a user's Local AppData* — the only form that can name ANOTHER account's copy |
  | `LW_LAUNCHER_EXE` | `LastWarLauncher.exe` | the launcher's filename |
  | `LW_GAME_EXE` | `LastWar.exe` | the client's process name |
  | `LW_WINDOW_TITLE` | `Last War-Survival Game` | what a window search matches on |
  | `LW_WIN_PYTHON` | `C:\Python312\python.exe` | the interpreter child processes are started with |
  | `LW_PLAYER_LOG` | `…\AppData\LocalLow\<game folder>\Player.log` | where Lua results are read back from |
  | `LW_LOCALLOW` | `…\AppData\LocalLow` | Unity's `persistentDataPath` root |
  | `LW_GAME_DATA_DIR` | `<LocalLow>\<game folder>` | what the client **downloads** — a different tree from the install |
  | `LW_CHAT_PHOTOS` | `<data dir>\ChatPhotos` | the chat photo / avatar cache |
  | `LW_GAMERES` | `<install>\…\AssetBundles\gameres` | the asset index |
  | `LW_ASSET_CACHE` | `<install>\Cache\AssetBundles` | the downloaded-bundle cache |
  | `LW_WIRESHARK_DIR` | `/mnt/c/Program Files/Wireshark` | where `tshark` is, seen from WSL |
  | `LW_GAME_PORT` | `17935` | capture filter **fallback** — ask the live socket first |

  **Nothing here has to be set**, and adding a second account must never
  need it: the login names the session, the session's profile directory
  is a registry lookup, the ordinary install joins onto it.

  **Never expand a per-user path for somebody else.** `%LOCALAPPDATA%`
  is a different folder per account, so a configured launcher is passed
  to the other session *unexpanded* and resolved there against its own
  environment block (`tools/session_launch.py::expand_for`). Expanding
  it in the panel names the panel user's install and starts it from
  another account's token.

  `tests/test_game_paths.py` fails on a module that spells any of it out
  for itself again — which is how the panel's «launcher» default came to
  say `C:\Program Files\LastWar` while the shell said something else.

- **Never ship a personal value at all** — and a login is the worst of
  them. The project is public and gets installed on other people's
  machines, so a Windows account, a session, a home server or a squad
  UUID is **asked or registered, never defaulted**: `--user` /
  `LW_SECOND_USER` for a second client, `tools/data/instances.json` for
  a second instance, `.env` (`tools/lib/tool_config.py`) for the
  player's own numbers, with empty defaults so an unset value fails
  loudly rather than acting on somebody else's.

  A default naming the machine this was written on is worse than a wrong
  one: it does not say «not configured», it goes looking for a folder or
  a session that cannot exist and reports the ordinary «no client
  running».

  `tests/test_no_hardcoded_values.py` enforces both halves — quoted
  literals of the install, and personal logins anywhere in a tracked
  file. The full rule is in `CLAUDE.md`, «Nothing about one machine is
  written into the code».

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
- **A way back into the region picker** — `ui_region.RegionPickerWindow` still
  crops templates and copies `READ_TEXT` coordinates, and nothing opens it since
  the old window went. A panel tab, or a `__main__` on the module, plus the
  "save with an alpha-masked centre" flow it never got.
- **VLM ASK primitive** — `ASK_VLM "question" INTO profile.x` that
  sends the current capture to the configured `VisionProvider` and
  binds the answer. Needed when ambiguous screens require a smarter
  fallback than templates.
- **Loops by iteration**: `FOR EACH match IN FIND_ALL …` (depends on
  FIND_ALL).

---

## 10. Pointers — where to dig deeper

- **`docs/farming.md`** (RU mirror `docs/farming.ru.md`) — the feature list:
  what is automated, what is half-way, what is still done by hand. The
  README points a reader here first; keep the two in step.
- **`CLAUDE.md`** — the BINDING rules, and they override anything here: every
  ability is a scenario, every tab a plugin, every edit travels between the
  window and the phone, every string a locale key, nothing about one machine in
  the code, and both farming files updated once an ability is confirmed live.
- **`docs/architecture.md`** — the original v2 design, with a note on which parts
  of it were never built (the LLM planner and the VLM executor loop).
- **`docs/dsl.md`** — formal grammar (user-facing reference).
- **`docs/panel-tabs.md`** — how to write a panel tab (the how-to; the
  reasoning is `docs/research/panel-tabs-refactor.md` below).
- **`docs/actions-authoring.md`** — deep-dive recipes and primitive-
  authoring checklist.
- **`docs/game/`** — game knowledge: overview, daily cycle, glossary,
  per-screen notes. **`docs/game-glossary.md`** is the other half: the terms the
  GAME itself has words for, copied out of its own tables in all eleven panel
  languages (`tools/game_locale.py --term "…"` prints any other one).
- **`docs/install/`** — Windows install for a new operator.
- **`docs/research/`** — one file per ability, and this is where an
  implementation detail belongs (protocol names, Lua routes, wire fields).
  `panel-tabs-refactor.md` is the panel's migration plan — read it before
  touching `panel/__main__.py`; `multi-instance-rdp.md` is how a second account
  runs at all.
- **`docs/skills/`** — recording a sniffer session and turning it into a
  scenario. `sniff-quick.md` is loaded into every session by `CLAUDE.md`.

---

## 11. Status

**The honest, ability-by-ability answer is [`docs/farming.md`](docs/farming.md)**
(RU mirror `farming.ru.md`), with ✅ for proven live and 🟡 for half-way. It is
kept up to date by rule; this section is only the shape of things.

What exists:

- **The panel is the interface.** Tabs are plugins (`docs/panel-tabs.md`), it
  speaks eleven languages, several profiles are open at once each with its own
  client, and a phone opens the same runtime over the local network (#1221).
- **The game is driven headlessly**, through its own Lua VM by way of a warm
  daemon per client — collecting, donating, healing, recruiting, helping, the
  ministry, robberies, rallies, the client's own start/close/restart. Pixels and
  OCR are the minority path now.
- **Reading the world** — the map, secret tasks, ghost recon, rallies and chat
  are read off the game's own traffic and its Lua state, not the screen.
- **Two accounts on one machine**, the second in its own Windows session
  (§5 above).
- **Errands on a clock**, plus triggers that fire on a push from the wire; the
  list belongs to the profile, and a failed errand is retried whole instead of
  being counted as run.

What is not built: the **LLM planner** and the **VLM executor** of
`docs/architecture.md` — the bot acts through explicit scenarios, not a plan it
composed. And nothing sequences a WHOLE session by itself: the schedule can be
made to do it, but no ready-made daily routine ships (`docs/game/daily_cycle.md`
holds the order and the timing constraints if you build one).

Good luck — and when in doubt, **default to a script change**.
