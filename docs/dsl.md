# Action scripts — DSL reference

Skills live as small declarative scripts in `src/lastwar_bot/actions/*.md`.
Each file is one skill; the file name (without `.md`) is the skill name.
The runtime is implemented in `src/lastwar_bot/script_engine.py`.

> **Blessed vs. dev.** Only tested scripts sit in `actions/`; the rest live in
> `actions/dev/` (still runnable — `run_action`/`CALL` look in both). The panel offers
> the blessed dir only. Several examples below reference files now under `actions/dev/`.

## A complete example

`go_to_base.md`:

```
# Navigate to the Base screen if we're not already there.

IF screen != base
    CALL click_base_button
    WAIT screen == base WITHIN 10s
```

`click_base_button.md`:

```
# Locate the bottom-right toggle whose icon takes us to Base, then click it.

FIND toggle_to_base.png
    CLICK
```

Reading top-to-bottom: when called, `go_to_base` first asks "is the
current screen NOT base?". If yes, it calls another script
(`click_base_button`) which finds the right button on the screen and
clicks it, then waits up to 10 seconds for the screen to become "base".

## Statements

All keywords are case-insensitive. One statement per line. Blank lines
and lines starting with `#` are comments.

### `IF condition` / `ELSE`

Run the indented block when the condition is true (or false for `ELSE`).
Both branches are optional bodies; the `ELSE` clause is optional.

```
IF screen == world
    CALL collect_world_items
ELSE
    LOG "Not on world, skipping"
```

### `WHILE condition [LIMIT N]`

Repeat the indented body while the condition is true. `LIMIT` caps the
number of iterations as a safety against infinite loops (default 20,
applied silently if no `LIMIT` clause is given). When the condition
becomes false the loop exits cleanly; when the LIMIT is hit while the
condition is still true the runtime logs a "LIMIT N reached" line and
continues with the next statement.

```
WHILE screen == unknown LIMIT 8
    PRESS ESC
    WAIT 0.4
```

### `PRESS <key>`

Send a single key press to the game window (foreground, real input —
DirectInput games ignore message-based key delivery). Supported names:
`ESC`, `ENTER`, `SPACE`, `TAB`, `BACKSPACE`, `DELETE`, `HOME`, `END`,
`PAGEUP`, `PAGEDOWN`, `UP`, `DOWN`, `LEFT`, `RIGHT`, `F1`..`F12`, plus
any single letter or digit (`A`, `Z`, `5`, …).

```
PRESS ESC
PRESS F5
```

### Template files and alpha masks

Every `<name>.png` reference resolves to a file in
`src/lastwar_bot/game/templates/`. Plain RGB PNGs are matched as-is.
PNGs with an **alpha channel** are treated specially: pixels where
`alpha < 128` are *not* used for keypoint extraction. This is the way
to match a UI element whose centre is dynamic (a frame around a number,
a card whose body shows live game content, …) — only the stable outline
contributes to the match, the dynamic centre is ignored. The bounding
box and centre reported by the match still cover the full original
template area, so a subsequent `CLICK` lands on the icon's centre as
usual.

Workflow: capture the template (e.g. via the UI's Pick region) and
erase the dynamic part to transparent in any image editor (GIMP /
Photoshop / Paint.NET).

### `FIND <template>.png`

Search the current screen for the named template (PNG file under
`src/lastwar_bot/game/templates/`). Indented statements run **only if
the template was found**, and they may use `CLICK` (no argument) to
click the match's centre. After a successful FIND, the match is saved
as the **LAST** result, used by the next `CLICK`.

```
FIND inventory.png
    CLICK
```

If the template doesn't match, the body is skipped (no error). The
script continues with the next sibling statement.

### `CLICK` / `CLICK (x, y)`

Two forms:

- `CLICK` — click the centre of the most recent successful `FIND`.
  Fails the script if there was no prior `FIND` or it didn't match.
- `CLICK (x, y)` — click absolute client coordinates. Useful for UI
  elements that can't be reliably found by template, e.g. the player
  avatar whose art changes per account.

```
CLICK (50, 50)
FIND inventory.png
    CLICK
```

### `READ_TEXT (x, y, w, h) INTO profile.<field>`

OCR the rectangular region `(x, y, w, h)` of the current screen
(coordinates in client pixels) and write the recognised text into the
named profile field. The active profile must be loaded — pass
`--profile <id>` when starting the bot.

```
READ_TEXT (300, 100, 400, 60) INTO profile.name
READ_TEXT (300, 180, 200, 50) INTO profile.level
```

Each assignment writes the field to disk immediately
(`./profiles/<profile_id>.json`). Empty OCR result is stored as an
empty string. Values are stored as text; downstream conditions
compare them as strings (e.g. `profile.level == "50"`).

### `CALL <action_name>`

Execute another script by name (e.g. `CALL click_base_button` runs
`actions/click_base_button.md`). The sub-script's failure propagates —
the calling script also fails.

### `WAIT condition [WITHIN N s]`

Poll the condition repeatedly until it becomes true, or fail after the
timeout (default 10 seconds). Useful right after a click to let an
animation settle.

```
WAIT screen == base WITHIN 15s
```

A special form, `WAIT N` (or `WAIT N s`), is a plain fixed-duration
sleep:

```
WAIT 1.5
```

### `LOG "message"`

Emit the message to the runtime log. Useful for tracing branches.

```
IF screen == unknown
    LOG "Don't know where we are; bailing out"
```

### `STOP ["reason"]`

Signal that the bot should halt entirely. Unwinds all enclosing blocks
and sub-actions. The runner notices the halt flag on the shared context
after the action returns and stops itself. Optional quoted reason is
surfaced in the log.

Typical use is inside a watchdog: if a condition requires immediate
abort, set the reason and stop.

```
FIND kicked_modal.png
    LOG "Another login detected"
    CLOSE_WINDOW
    STOP "kicked by another login"
```

### `CLOSE_WINDOW`

Send a `WM_CLOSE` message to the game window. This is the polite way to
ask the client to shut down (no force-kill). Pair with `STOP` to also
halt the bot.

### `LAUNCH "path/to/exe"`

Spawn a process (typically the game launcher) as a detached child. The
path is quoted so spaces and backslashes need no escaping. The script
returns immediately — pair with `WAIT screen == base WITHIN 300s` to
block until the game is ready.

The path string is passed through `os.path.expandvars` and
`os.path.expanduser`, so it can contain:

- Windows-style env vars: `%LOCALAPPDATA%\\FunFly\\...`
- POSIX-style env vars: `$HOME/games/...`
- Home directory shortcut: `~/games/...`

```
LAUNCH "%LOCALAPPDATA%\FunFly\Last War-Survival Game\LastWarLauncher.exe"
WAIT screen == base WITHIN 300s
```

Scripts that begin with `LAUNCH` run before the game window exists. The
runtime detects this and lazily re-finds the window on each WAIT
iteration, so the same `WAIT screen == ...` form works whether the
window already exists or is about to appear.

### `SCAN_SECRET_MISSIONS [LEVEL n] [STAR] [CAN_LOOT] [FREE_SLOTS n] [WITHIN N s]`

Find secret tasks (hero dispatch) by reading the game's own network
traffic instead of the screen. The result lands in the `MISSIONS`
register and is queried with the `missions.count` condition; each match
is written to the run log with its level, coordinates and loot count.

This is the only primitive that does not look at pixels. Secret-task
tiles cross the wire as exact numbers, so level, position and "who has
already looted this" need no OCR. See `docs/research/protocol.md` §7.

```
SCAN_SECRET_MISSIONS LEVEL 7 STAR CAN_LOOT WITHIN 30s
IF missions.count > 0
    LOG "Found something worth raiding."
```

Modifiers are optional and order-independent:

| Modifier | Effect |
|---|---|
| `LEVEL n` | only tasks of level `n` (decoded from `cfgId`) |
| `STAR` | only starred tasks (`cfgId` family `6000`), see below |
| `CAN_LOOT` | at least one of the three loot slots still free |
| `FREE_SLOTS n` | stricter form: at least `n` of three free (`3` = untouched) |
| `WITHIN N s` | how long to listen; returns early on the first match (default 30 s) |

An unknown modifier is a **parse error**, not a warning — a silently
ignored `STAR` would send the bot after the wrong tasks.

Two things to know before relying on it:

- **The map must be moving.** The game only sends map data while the map
  scrolls. A stationary map produces no tiles and the scan will honestly
  report zero. Run it while panning.
- **Wireshark must be installed** — the scan drives its `dumpcap`
  capture engine. Missing capture tooling raises; an empty result does
  not (that is a legitimate answer, branch on `missions.count == 0`).

`STAR` matches `cfgId` family `6000`. The star is not a field on the
wire — the client derives it from `cfgId`, the same place the level
hides — so the rule lives in one constant, `STAR_TASK_FAMILIES` in
`tools/lastwar_proto.py`, where the evidence behind it and the one
observation that does not yet fit are both written down. Re-test it any
time with `tools/live_tshark.py --tasks --families`, which tallies
families against the stars actually drawn on the map.

## Game primitives (Lua VM, no pixels)

Everything above reads the screen and clicks. These instead drive the game through
its **own Lua VM** — the warm daemon in `tools/lua_daemon.py` (see
`docs/research/xlua-state.md`). They send exact in-engine calls, so they are immune
to UI-layout drift and OCR noise, and they need **no game-window handle** — an action
made entirely of game primitives runs even when started with `hwnd=0` (e.g. from the
panel's Scenarios tab). The daemon must be up; if it is down the evaluator falls back
to a fresh local `LuaEval`.

The evaluator is created on first use and cached on the run context, so every game
primitive in one action shares one connection.

**Two layers, so recipes stay readable.** The everyday layer is `TAP` — you press
*named buttons* (`alliance`, `donate_1000`, …) and never see an engine name. The ugly
`UIManager.Instance:OpenWindow(...)` calls behind each button live in one catalogue,
`tools/lib/game_buttons.py`. Underneath sits the authoring layer — `LUA`, `READ_LUA`
and the `GAME`/`JUMP` sugar — which is how you *define* a new button or write a
one-off flow. A finished recipe should read like a list of button presses.

> **Never put a server-waiting loop inside one `LUA` chunk.** The chunk runs on the
> game's main thread and returns at once; a Lua `while` that waits for a value the
> server sends back (a donation count, a load flag) spins forever and freezes the
> client. Loop in the DSL instead — `TAP ... xN`, or `WHILE` + `WAIT` — so the
> round-trip lands between calls. Each `TAP` already pauses after every press.

### `TAP <button> [xN | xall]`

Press a named button from the catalogue — once (default), `N` times, or `xall`. This
is the human-facing primitive: the recipe names *what* to press, the catalogue knows
*how*.

```
TAP alliance_tech     # open Alliance Tech
TAP recommended_tech  # open the priority tech
TAP donate_1000 xall  # press "Donate 1000" for every attempt currently banked
TAP close x3          # pop 3 windows off the stack
```

`xall` presses **as many times as the button reports it still can** — its `count_lua`
in the catalogue (for `donate_1000`, the remaining-donations count). The real number
is read at run time and substituted for you, and the loop re-reads it after each press
and stops at zero, so it spends exactly what is available and recovers any press the
client's long-press throttle dropped. (There is no single "donate all" call in the
game — the in-game *hold* just repeats the click at an interval; `xall` reproduces
that, fast.) A button with no `count_lua` cannot be `xall`'d (clear runtime error).

Every button carries its own small post-press pause (in the catalogue), so even a long
`xall` never busy-loops the client — the throttle/round-trip lands in the gap.
Pressing more times than there is anything to do is harmless when the action
self-gates (`donate_1000` no-ops once the quota is spent). An unknown button name is a
runtime error listing the ones that exist.

**Adding a button** = one entry in `tools/lib/game_buttons.py` (`name -> {lua, wait,
label, count_lua?}`). Use `READ_LUA`/`LUA` while working it out, then fold the call
into a button so recipes can just `TAP` it.

### `LUA <chunk>`

Run one raw Lua chunk in the game VM. The rest of the line, verbatim — no quotes
(Lua is quote-heavy). Errors are caught and logged rather than silently swallowed.

```
LUA UIManager.Instance:OpenWindow(UIWindowNames.UIAllianceScience)
LUA local rec = DataCenter.AllianceScienceDataManager:GetCurRecommendScience(); UIManager.Instance:GetStackTopWindow().Ctrl:OnScienceInfoClick(rec, nil)
```

### `READ_LUA <expr> INTO <var>`

Evaluate a Lua expression and store its value in a script variable. Numeric results
become numbers (so `IF`/`WHILE` can compare them); anything else stays a string. The
`INTO <var>` tail is anchored at the end of the line, so the expression can contain
anything up to it.

```
READ_LUA DataCenter.AllianceScienceDataManager:GetResDonateRestCount() INTO attempts
READ_LUA (UIManager.Instance:GetStackTopWindow() and 1 or 0) INTO haswin
```

Variables are then tested with a **numeric condition** in `IF`/`WHILE`:
`<var> <op> <number>`, where `<op>` is `==`, `!=`, `>`, `<`, `>=`, `<=`. Testing a
variable that was never set, or one holding a non-numeric value, is a runtime error.

```
WHILE attempts > 0 LIMIT 40
    LUA ... one "Donate 1000" press ...
    WAIT 0.6
    READ_LUA DataCenter.AllianceScienceDataManager:GetResDonateRestCount() INTO attempts
```

This `WHILE`/`READ_LUA` shape is how you spend *exactly* the banked attempts and stop
(rather than a fixed `TAP donate_1000 x30`); it is the pattern to reach for when a
count must gate the loop. The engine API behind the alliance-science calls is in
`docs/research/alliance-tech-donate.md`.

### `GAME WORLD` / `GAME CITY`

Switch the scene: `WORLD` renders the map, `CITY` returns to the home base. Wraps
`SceneUtils.ChangeToWorld()` / `ChangeToCity()`.

```
GAME WORLD
```

The vision-based `go_to_world.md` clicks the on-screen toggle instead; use whichever
fits — the Lua path is layout-proof, the vision path needs no daemon.

### `JUMP x, y [, server]`

Jump the camera to tile `(x, y)`. With no server it stays on the current/home server;
with a third number it enters that server (cross-server jump). Wraps the game's own
coordinate-jump, `GoToUtil.GotoWorldPos`.

```
JUMP 512, 640
JUMP 512, 640, 972
```

## Conditions

Allowed in `IF` and `WAIT`:

- `screen == base` / `screen != base`
- `screen == world` / `screen != world`
- `screen == unknown` / `screen != unknown`
- `FOUND` — last `FIND` succeeded
- `NOT FOUND` — last `FIND` returned nothing
- `FIND <name>.png` — ad-hoc SIFT search now; true if visible. **Side
  effect**: on success updates `LAST` so the next `CLICK` lands on the
  match.
  ```
  WAIT FIND profile_modal_marker.png WITHIN 5s
  IF FIND popup_close.png
      CLICK
  ```
- `profile.<field> == "<text>"` / `profile.<field> != "<text>"` — string
  comparison against a field of the active profile. Missing field is
  treated as the empty string.
  ```
  IF profile.server == "972"
      CALL alliance_specific_thing
  ```
- `missions.count <op> <n>` where `<op>` is `==`, `!=`, `>`, `<`, `>=`
  or `<=` — how many secret tasks the last `SCAN_SECRET_MISSIONS`
  matched.
  ```
  IF missions.count == 0
      LOG "Nothing in view; scroll and scan again."
  ```

(More predicates are added as new primitives appear — extend
`Interpreter.eval_condition`.)

## Watchdog

The runner's tick loop runs a special action called `watchdog.md` (if
present) on every tick *before* the main heartbeat. The watchdog is the
designated place for "react to interrupt conditions" logic — modals
that need acknowledgment, network errors that warrant a shutdown,
account-locked dialogues, etc.

If the watchdog executes a `STOP`, the runner halts immediately and
won't run further ticks. Combine with `CLOSE_WINDOW` to also close the
game cleanly.

To disable, leave `watchdog.md` empty (only comments) or pass
`watchdog_action=None` to `BotRunner`.

## Profiles

Each operator of the bot picks a **profile id** on startup:

```
python -m lastwar_bot.ui --profile alice
```

The profile is loaded from `./profiles/<id>.json` (created on first
write). Scripts read fields via `profile.<field>` conditions and write
fields via `READ_TEXT (...) INTO profile.<field>`. The default profile
id is `default`.

A typical onboarding action — see `actions/capture_profile.md` — opens
the in-game profile modal and OCRs the player's name, level, and
server number into the profile. Other actions can then branch on the
captured values:

```
IF profile.server == "972"
    CALL alliance_972_routine
```

Profiles are persisted to disk on every write. The `profiles/` folder
is gitignored.

## References — what's a template, what's a script?

- A token that ends in `.png` is a **template** file, resolved against
  `src/lastwar_bot/game/templates/`.
- A token used after `CALL` is an **action name** (another `.md` script
  in `src/lastwar_bot/actions/`).

There's no implicit dispatch — you always say `FIND foo.png` or
`CALL foo`. No quotes, no brackets.

## Implicit state

While a script runs, the interpreter keeps a few pieces of state:

- `LAST` — the most recent successful `FIND` result (the match's centre
  point, in client coordinates). Reset to "none" when a `FIND` returns
  no match. Consumed by bare `CLICK`.
- `screen` — recomputed live from the current capture each time a
  condition evaluates `screen ==` or `screen !=`. So your script always
  sees the latest screen state, not a stale cache.
- `profile.<field>` — bound to the active profile loaded from
  `./profiles/<profile_id>.json`. Selected at launch with
  `--profile <id>` (defaults to `default`). Reads via the
  `profile.<field>` condition; writes via `READ_TEXT ... INTO
  profile.<field>`, which persists to disk immediately.

## Failure model

Every action returns OK / FAILED. An action fails when:

- An assert-like primitive raises: `CLICK` with no prior `FIND`, `WAIT`
  that times out, an unknown condition or keyword, a missing template /
  script file.
- A nested `CALL` fails (propagates).

A `FIND` that doesn't match is **not** a failure on its own — it simply
skips its body. Wrap it in an `IF FOUND ... ELSE ...` if you want to
react explicitly.

## Style

- Indent with 4 spaces (the parser accepts any consistent step, but 4
  is the convention).
- One statement per line.
- Keep each script tightly scoped to one concept. Compose larger flows
  with `CALL`.
- Prefer comments for *why*, not *what*.

## How an LLM is supposed to use this

This grammar is the contract the LLM works against:

1. Read the natural-language scenario from the user.
2. Reuse the existing primitives and templates wherever possible.
3. Generate a new `.md` file (or edit an existing one) using only the
   keywords above. Don't invent new ones — propose them in a comment
   if needed, and a maintainer will extend the runtime.

The shorter the grammar stays, the safer LLM-authored scripts are.
