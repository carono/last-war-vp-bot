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

### `ARGS <name> = <default>`

Declare a parameter of the script and its default. The caller's value wins; the
default is what lets the same script run with no arguments at all.

```
ARGS squads = [1, 2, 3]
ARGS leader = Rock
```

The value is JSON when it parses as JSON (numbers, lists, `true`/`false`,
`"quoted"`) and plain text otherwise. Declarations are stripped before parsing —
they describe the signature, not the body — and may sit anywhere, though the top
of the file is where a reader looks for them.

Arguments are then used two ways:

- **`{name}` anywhere in the text** is replaced by the value *before the script is
  parsed*, so an argument can appear in any statement, not just where a variable
  would fit:

  ```
  LUA DataCenter.__lw_rally_squads = { {squads} }
  ```

  A list renders as its comma-separated items (hence `{ {squads} }` → a Lua
  table), a bool as Lua's `true`/`false`. The replacement is textual and
  name-keyed, so a Lua table of the script's own (`{a=1}`, `{}`) is untouched, and
  an unknown `{placeholder}` is left standing where the log will show it.
- **as a script variable**, so `IF` / `WHILE` can test it: `IF squads > 0`. Same
  store `READ_LUA … INTO x` writes to.

Because substitution happens once, before the run, `{x}` carries the value the
script *started* with; a variable a later `READ_LUA` overwrites is read with a
condition, not with `{x}`.

Callers: the panel's Scenarios tab has an «аргументы (JSON)» box, a timer passes
its `args` block (see `panel/timers.py`), and from Python it is
`run_action(name, hwnd=0, variables={...})`.

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

### `FAIL ["reason"]` (also `RETURN FAIL`)

End the run as a **failure**. The mirror image of `STOP`: `STOP` ends the
run as a deliberate success (the scenario decided it is done), `FAIL`
ends it as a deliberate failure — the action returns `False`, unwinding
all enclosing blocks and sub-actions. Optional quoted reason is surfaced
in the log.

Use it for a precondition the scenario cannot meet right now, so a
**timer retries it** (after the timer's `retry_sec`) instead of counting
a run that did nothing as done. The canonical case is "only works on the
base":

```
IF scene != city
    FAIL "not on the base (need the city scene) — retry later"
TAP collect_visitor_gifts xall
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

`LAUNCH` is the generic "spawn a process" statement and it always spawns
it **here**, on the desktop the bot is running on. To start the *game
client* use `START_GAME` below, which knows where this profile's client
lives.

### `START_GAME ["path/to/launcher"] [WITHIN N s]`

Start the game client **this profile drives**, in the Windows session it
lives in. The opening half of what `QUIT_GAME` closes, and it has the
same trap the other way round: a profile farming a second account runs
its client in a Windows session of its own
(`tools/rdp_instance.py`), and a launcher spawned from here would put a
*third* client on this desktop while the account that was asked for
stayed down.

Which session is the profile's business, and the panel hands it to the
run as `Context.game_user` — the login of the session's user. Nothing
else can answer it at launch time: `QUIT_GAME` finds its client through
the daemon *attached* to it, and there is no client to attach to yet.

Two routes, picked by whether a session is named:

- **no session — this desktop.** Exactly what `LAUNCH` does: spawn the
  launcher as a detached child, return at once. Nothing is waited for;
  the readiness test is the `WAIT scene == city` that follows.
- **a session — that session,** through `tools/session_launch.py`, which
  starts the launcher under the token that is *already* that session's
  interactive logon. That is the only arrangement the game's anti-cheat
  accepts (`docs/research/multi-instance-rdp.md`): the process user and
  the session owner are the same account, the launch is merely issued
  from outside. It needs `SeTcbPrivilege`, so it goes through the SYSTEM
  hop `tools/rdp_instance.py` owns — one silent elevation and a
  throwaway scheduled task, the same route `--bring-up` takes. This
  route then **waits for the client**, not for the launcher, because
  `LastWarLauncher.exe` updates itself and only then spawns the game.
  Default window: 300 s, `WITHIN` overrides it. A client already running
  in that session is the job already done, not an error.

**Where the launcher is, is not written in the scenario.** A scenario is
the same file on everybody's machine and an install is not, so
`launch_game.md` says a bare `START_GAME` and each side resolves its own
copy — `tools/lib/game_paths.py`, which reads the environment first:

| variable | default | what it is |
|---|---|---|
| `LW_LAUNCHER` | *(built below)* | the launcher — an override for an install that is not ordinary |
| `LW_GAME_DIR` | `%LOCALAPPDATA%\FunFly\Last War-Survival Game` | the install folder |
| `LW_GAME_FOLDER` | `FunFly\Last War-Survival Game` | the same folder *relative to a user's Local AppData* |
| `LW_LAUNCHER_EXE` | `LastWarLauncher.exe` | the launcher's filename |
| `LW_GAME_EXE` | `LastWar.exe` | the client's process name |

**None of it has to be set.** Adding a second account is a tick and a
login: the session names the account, the account's profile directory is
a registry lookup, and the ordinary install joins onto it. A path typed
by hand is never required, and `--game-folder` / `--launcher-exe` carry
the pieces over the SYSTEM hop because that hop inherits nothing from
the panel.

**A configured path is expanded where it means something.** `LW_LAUNCHER`
travels to the other session **verbatim**, and is expanded there against
that session's own environment block — the one place on the machine
where the target account's `%LOCALAPPDATA%` is correct. So
`%LOCALAPPDATA%\Acme\Custom.exe` names *each* account's own copy, and
`D:\Games\LW\Boot.exe` names one file for all of them; both work, and
neither is expanded in the panel, which would name the panel user's
folder and then start it from somebody else's token.

The optional quoted path overrides the variable and follows the same
rule.

A launcher that is not where the path says is a blow-up (a configuration
mistake). Nobody logged on as that user, or a client that never
appeared, is a deliberate `FAIL` with words — a condition to try again
later, which is what a timer does with it.

**A session that does not exist is not created here.** Making one means
an RDP connection, saved credentials, and the console changing hands
while it happens; doing that behind a «Запустить игру» press would be a
surprise, so the failure names the command that does it instead
(`tools/rdp_instance.py --bring-up --user <login>`). A *disconnected*
session is not this case at all — it is a working session with a desktop
of its own, which is how the second client is meant to be left, and the
launch goes into it unchanged.

```
START_GAME
WAIT scene == city WITHIN 300s
```

That is `actions/launch_game.md`, which the panel's «Запустить игру»
plays and `restart_game` calls.

### `QUIT_GAME`

End the game client **this profile drives**, and wait until the process
has really gone. Unlike `CLOSE_WINDOW` this is a force close: half the
reason to end a client is that it has stopped answering, and a window
ignoring `WM_CLOSE` would turn the statement into a long wait for
nothing.

*Which* client is the part that matters. With two accounts on one
machine there are two clients, one per Windows session, each with its
own Lua daemon on its own port — so the target is the process **this
profile's daemon is attached to**, never "the LastWar.exe" by name
(`tools/lib/game_client.py` resolves it: the daemon's attachment, then
`LW_GAME_PID`, then the client in this Windows session). Closing by
image name would end the other account's session too.

When the profile names a Windows session (`Context.game_user`), the
lookup gets **narrower**, not wider, and both halves of that matter:

- the fallback never reaches this desktop's client. `running_pid` means
  "the client of *this* session", which for a profile playing in session
  4 is the neighbour's game — and the next thing that happens is not a
  read but a kill;
- the daemon's own answer is checked against that session before it is
  believed. A daemon started on the wrong desktop binds the right port
  and hijacks the wrong client, which is not hypothetical: that is
  exactly what was found running when #1218 went looking, and a restart
  that trusted it would have force-closed the game in front of the
  person.

Ending it needs rights this process may not have. `TerminateProcess` on
a process owned by another account comes back ACCESS_DENIED for an
unelevated panel, so that case is retried through **one elevated
`taskkill /F /PID`** — by pid, never by image name. The fallback fires
only when a session was named; a profile on this desktop that cannot
kill its own client has something else wrong, and a surprise elevation
prompt is not how to discover it. (Note that this is a *smaller*
privilege than `START_GAME` needs: starting a process inside somebody
else's session takes SYSTEM, ending one takes an administrator.)

A client that is not running is not an error — the statement's job is to
leave nothing running, and that is already true.

It also lets go of this run's link into the game VM, so whatever follows
resolves a fresh one instead of driving a dead process id.

### `ATTACH_GAME [WITHIN N s]`

Point the warm Lua daemon at the client that is running **now**, and
block until it is attached. The daemon caches one resolved evaluator per
client process, so after a restart that cache names a pid that no longer
exists; it repairs itself on the first failing call, but that repair
would land inside whatever runs next and read as *that* failing. This
statement does the handover where it belongs, and fails when the client
never came back.

With no daemon running there is nothing warm to re-point (the next game
primitive builds its own evaluator, which finds the live client itself),
so the wait is for the **client**, and re-pointing is best-effort on top
of it. Default window: 120 s.

Both statements end the run as a deliberate `FAIL` with words — "no
client is running", "the daemon would not attach to it" — rather than as
a blow-up, because a client that has not come back is a thing to try
again later, and the timer row shows the reason verbatim.

A daemon started pinned to one client (`lua_daemon.py --pid …`, or
`LW_GAME_PID`) follows that client into its new process rather than
refusing to attach to a pid that no longer exists — but only within its
own Windows session, so a restart on one account never re-points it at
the other's game.

```
QUIT_GAME
WAIT 3
CALL launch_game
ATTACH_GAME WITHIN 120s
```

That is `actions/restart_game.md` — the whole of "restart the client",
which the panel plays on a clock.

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
TAP alliance_tech           # open Alliance Tech
TAP donate_1000 xall        # press "Donate 1000" for every attempt currently banked
TAP collect_base_resources  # harvest every ready resource building in one sweep
TAP close x3                # pop 3 windows off the stack
```

`xall` presses **as many times as the button reports it still can** — its `count_lua`
in the catalogue (for `donate_1000`, the remaining-donations count). The real number
is read at run time and substituted for you, and the loop re-reads it and stops at
zero, so it spends exactly what is available and recovers any press the client's
long-press throttle dropped. (There is no single "donate all" call in the game — the
in-game *hold* just repeats the click at an interval; `xall` reproduces that, fast.)
A button with no `count_lua` cannot be `xall`'d (clear runtime error).

**Repeats are batched where the button allows it.** A call into the game VM costs
~0.15 s and the Lua loop inside it is free, so a button may declare a `batch_lua` —
the same press written as an `n`-times loop — and then `xN` / one round of `xall`
becomes a single call rather than one per press. `donate_1000` does: a whole
30-attempt quota is spent in about a second instead of half a minute. Only a
fire-and-forget send can be batched; anything that has to see the server's answer
between presses must not be (see the freeze warning above).

Every button carries its own small post-press pause (in the catalogue), so even a long
`xall` never busy-loops the client — the throttle/round-trip lands in the gap.
Pressing more times than there is anything to do is harmless when the action
self-gates (`donate_1000` no-ops once the quota is spent). An unknown button name is a
runtime error listing the ones that exist.

**Adding a button** = one entry in `tools/lib/game_buttons.py` (`name -> {lua, wait,
label, count_lua?, batch_lua?}`). Use `READ_LUA`/`LUA` while working it out, then fold
the call into a button so recipes can just `TAP` it.

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

- `scene == city` / `scene == world` / `scene == unknown` (and `!=`) — **state,
  not pixels.** Asks the game's own Lua VM (`SceneUtils.GetIsInCity/GetIsInWorld`,
  plus `UIMain` open for `city`). Reads `unknown` while the client is loading or the
  daemon is re-hijacking a freshly-launched process, and needs no game window — so it
  works right through a launch/restart (`WAIT scene == city WITHIN 300s`). **Prefer
  this** over `screen`.
  ```
  WAIT scene == city WITHIN 300s
  IF scene == world
      LOG "on the map"
  ```
- `screen == base` / `screen != base` — **legacy SIFT vision** (screenshots the
  window and feature-matches templates). Needs `cv2` + the game window; only the
  `actions/dev/` vision scripts still use it. Prefer `scene` for anything new.
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

## Running one from Python

`script_engine` exposes three entry points beyond the CLI runner:

```python
run_action("collect_base_resources", hwnd=0, on_event=print)   # a file in actions/
run_text('LOG "hi"\nWAIT 1', on_event=print)                   # source held in memory
ctx = new_context(variables={"count": 3})                      # one session, many calls
run_action("a", hwnd=0, ctx=ctx); run_text("TAP close", ctx=ctx)
```

Passing the same `ctx` to several calls runs them as one session: variables, the
last `FIND` and the Lua evaluator are shared, so a sequence costs one daemon
connection rather than one per step. `variables` seeds the same store
`READ_LUA … INTO x` writes to, so a caller can hand a script its parameters and
the script tests them with the ordinary `IF x > 3` conditions.

Both forms are what the panel's schedule runs (each profile's
`panel/profiles/<name>/timers.json`): a step that names an action file runs the
file, and anything else is treated as source.

## Failure model

Every action returns OK / FAILED. An action fails when:

- An assert-like primitive raises: `CLICK` with no prior `FIND`, `WAIT`
  that times out, an unknown condition or keyword, a missing template /
  script file.
- A nested `CALL` fails (propagates).

A `FIND` that doesn't match is **not** a failure on its own — it simply
skips its body. Wrap it in an `IF FOUND ... ELSE ...` if you want to
react explicitly.

**Stopping from outside.** A caller can pass `cancel=<threading.Event>` (or set
`ctx.cancel`); the interpreter checks it between statements, between the presses
of a `TAP` repeat and between the polls of a `WAIT`. A set flag unwinds through
the same path `STOP` uses — the run ends **halted, not failed**, and never in the
middle of a call into the game. That is what the panel's «Стоп» button sets.

## The title line (and its translations)

A script's **first `#` line is its title** — what the control panel's Scenarios
picker shows instead of the bare file stem. Any of the leading comment lines may
carry a two-letter language tag, and the panel prefers the one matching the UI
language:

```
# Claim the alliance gifts — ordinary and premium.
# ru: Подарки альянса — обычные и премиальные.
```

The untagged line is the fallback, so a script with no tags keeps working exactly
as before and translating one is adding a line to it. Keep the title one sentence
about what the script does in the game — the paragraphs below it are for the
reader of the file, not for the picker.

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
