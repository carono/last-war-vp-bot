# Several profiles open at once, in one panel

A design document, written beside `panel-tabs-refactor.md` and against the shape that
refactor left behind.

The goal, in the operator's own words:

> нужно иметь возможность открыть профиль и запустить там демона для управления игрой,
> так в один момент на одной панели будут работать и свои таймеры и свои демоны не
> мешая друг другу

So: **one window, several profiles open at the same time.** Each with its own daemon,
its own client, its own schedule, its own settings, its own log — running in parallel
and out of each other's way. Including a profile whose client lives in its own Windows
session (`tools/rdp_instance.py`, and #1204's session login).

Read against `panel/__main__.py`, `panel/runtime/` (17 modules), `panel/tabs/`,
`panel/profile.py`, `tools/lib/game_lease.py`, `tools/lua_daemon.py`,
`tools/rdp_instance.py`.

> **State of play.** Waves 1 and 2a of §8 have already landed on master under this task
> — `c7e65db` (runtime isolation) and `1d0da8d` (`ProfileSession` / `Workspace` /
> `SessionScoped`), with `tests/test_panel_multi_profile.py` (18 cases) and
> `tests/test_panel_workspace.py` (20). Nothing in the shell has been touched, so a
> panel still opens exactly one profile and behaves exactly as it did. The waves below
> are marked accordingly; everything from 2b on is unwritten.

---

## 1. Why, in numbers

Two accounts today means two panels: two windows, two logs, two Settings pages, two
copies of the update check, two things to close. And the second one is not merely
inconvenient — it is **wrong in ways nothing reports**, because half of "which client am
I driving" was held by the *process* rather than by the profile:

| Held by the process | What two profiles did to it |
|---|---|
| `os.environ["LW_GAME_LEASE"]` | one variable, two rights: the second to claim overwrote the first's token; the first to release deleted the second's live one |
| `lua_client.PORT`, read from the environment at import | every in-process scenario went to 47654 whatever the profile said |
| the debug log's single file handler | both profiles into whichever configured last; the other's `debug.log` simply stopped |
| `panel/settings.json`'s `active_profile` | the second runtime silently redefined which profile "the panel" was on |
| `~/.last_war_panel.json` | the last window built renamed the machine's language |

The port one was **already wrong with a single profile**: a profile on 47655 drove the
second session's client from its captures and its children (they get `LW_DAEMON_PORT`
from `ChildFactory.env()`) and pressed its *scenarios* — which is most of what the panel
does — into the console session's client. That is fixed (wave 1); it is recorded here
because it is the shape of the whole problem.

---

## 2. What is already true, and why this is not a rewrite

The tabs refactor (#1184, seven waves, all done) built the thing this needs and never
used it for this:

* **`PanelRuntime` is per-profile, not per-process.** It owns the profile manager, the
  settings binder, the translator, the log sink, the ticker, the child factory, the game
  link, the action runner and the schedule. Nothing about it says "the one".
* **A tab talks to nothing but its runtime.** That is the binding rule in `CLAUDE.md` and
  the contract test enforces it. A tab of a hidden profile is therefore *already* correct
  — it holds its own `rt` and cannot see the shell.
* **A second runtime is already constructed today.** `panel/tabs/base.run_tab` — what
  `python -m panel.tabs.rally` runs — builds a whole second `PanelRuntime` around a bare
  root, and `host.standalone()` even re-points it at another daemon port.
* **The game lock is already the daemon's** (`tools/lib/game_lease.py`, wave 0 of #1184),
  which is exactly the mechanism two profiles need when they share a client.

What is missing is one level up: a *set* of runtimes, and a shell that is not written as
though there were one of everything.

---

## 3. The model

### 3.1 Three words

**Session** — one profile, open. Its runtime, its daemon link, its schedule, its tabs,
its log pane, its page. `panel/runtime/session.py::ProfileSession`.

**Workspace** — the set of sessions one window holds, plus which of them is on screen.
`panel/runtime/workspace.py::Workspace`.

**Window** — the `tk.Tk`: menu, geometry, splash, the update check, the About box. One
of each, however many profiles are open.

```
Panel (tk.Tk)                     menu · geometry · splash · updates · about
└── outer notebook                one page per OPEN PROFILE
    ├── «main» → ProfileSession   runtime · daemon :47654 · schedule · tabs · log · status
    └── «alt»  → ProfileSession   runtime · daemon :47655 · schedule · tabs · log · status
```

### 3.2 Where the boundary runs

**The whole runtime is per profile.** Not "a shared frame plus several sessions" — there
is nothing left in the runtime that is genuinely shared, and the five process-globals of
§1 are the proof of what happens when something pretends to be. The window keeps only
what is about the *window*.

| | Window | Session |
|---|---|---|
| menu bar, About, «Отправить диагностику» dialog | ✅ | |
| geometry, the resize damper, the paint suspension | ✅ | |
| the update check and its buttons (one checkout, one answer) | ✅ | |
| the splash and the boot progress | ✅ | |
| the profile dialog (create / rename / delete / open / close) | ✅ | |
| runtime, settings binder, translator, profile manager | | ✅ |
| daemon link, claim, client status strip | | ✅ |
| schedule: timers, triggers, their queue and listeners | | ✅ |
| the notebook of plugin tabs, and every tab in it | | ✅ |
| the log pane, its filter, its retention, `panel.log`, `debug.log` | | ✅ |
| the account summary strip, the map sweep, the watchdog counters | | ✅ |
| the DSL command line | | ✅ |

The one genuinely awkward case is **the language**. It is per profile (it is in
`config.json`) but the menu bar is the window's. Resolution: the Language menu acts on
the session whose page is showing, and the window's chrome is drawn in that session's
language. Switching pages re-renders the chrome. This is honest — the person is looking
at one profile at a time — and it is what already happens on a profile switch.

### 3.3 Everything runs; only the drawing follows the notebook

A session whose page is not on screen keeps its runtime, its schedule, its listeners,
its captures and its claim. That is the entire point of holding more than one open: the
second account is being farmed while you look at the first. `Workspace.switch_to` moves
the page and touches nothing else, and `tests/test_panel_workspace.py` pins it.

### 3.4 How the shell holds several without being rewritten

`panel/__main__.py` is ~2 900 lines of methods written against `self._rt`, `self._log`,
`self._game`, `self._dash_values`. Every one is correct and every one is about ONE
profile — the names already say so. Rewriting them all is a diff nobody can review
against a file three other tasks are editing, and it would say nothing new.

So the names are **declared** instead. `SessionScoped` (already written and tested) lets
a class name exactly which of its attributes are per-profile; reads and writes of those
go to the session whose page is showing, everything else is the window's. `self._log` in
a method keeps meaning "this profile's log widget" — there is simply more than one
profile for it to mean it about.

Three things keep that from being magic: the list is explicit and finite and a test
walks it; a declared name that is a property is never routed (so a mistake is inert);
and before there is a session nothing is routed at all.

**The one thing that is easy to get wrong is background work.** Routing answers "the
session whose page is showing", which is right for a button and wrong for a timer firing
while the operator is looking at another profile. The rule is:

> **Bind at the SCHEDULING site, never at the use site.**

`_arm()` binds what it arms — one change covering every timer loop. Each of the ten
`threading.Thread(target=…)` targets and each of the ten `self.after(…)` callbacks that
touch a declared name is wrapped once, where it is scheduled. A worker thread must not
touch a declared name directly; it computes and hops back. One place does today
(`_dash_loop` calls `_dash_tick` off the Tk thread) and is given its session explicitly.

The plugin tabs need none of this, which is §2's third bullet paying for itself.

---

## 4. Daemons

### 4.1 One daemon, one client, one port

That is already the model and the daemon enforces it: `lua_daemon.py` binds with
`SO_EXCLUSIVEADDRUSE`, so a second daemon cannot steal a live port and silently route a
session's calls into the wrong game. `--pid` / `LW_GAME_PID` pins which client it serves,
and `find_game_pid` prefers the client of the daemon's own Windows session.

A profile names its port in `daemon_port` (default 47654). **Nothing else changes:** two
profiles are two ports are two daemons are two clients. The panel-side plumbing that
makes that true — the link, the children's environment, the interpreter's target — landed
in wave 1.

### 4.2 Starting and stopping

`GameLink.ensure()` starts a daemon that is not up, `DETACHED_PROCESS` so it outlives the
panel; `restart()` asks the old one to exit and brings a fresh one up. Both are already
per-session. Two consequences worth stating:

* **A session does not stop its daemon when its page is closed.** The daemon is the
  client's, not the window's, and it deliberately survives the panel. Closing a profile
  releases that session's *claim* and stops its errands; the warm daemon stays for the
  next time. (If it should be stopped, that is a separate decision and a separate
  button — `Workspace.close` is the place, and it is one line.)
* **`ensure()` blocks for up to 30 s.** With N sessions that must not be N × 30 s of
  boot in series. The boot fans out: one thread per session, the splash waits for all of
  them.

### 4.3 Two profiles pointed at the same port

This is the case the operator will create by accident — copy a profile, forget to change
the port — and it must not look like it works. Two profiles on one port are **two views
of one client**, and there is exactly one honest behaviour: they take turns.

They already do, and correctly, because the lease is the *daemon's*:

* session A claims → the daemon issues a token;
* session B claims → the daemon answers `{"ok": false, "busy": "…", "held_sec": n}`, and
  `GameLink._claim_lease` logs `busy.elsewhere` and refuses;
* B's timer returns "the game is busy, try later" and is re-queued, which is what
  `run_errand` already does for a refused claim.

`tests/test_panel_multi_profile.py::test_two_links_on_ONE_daemon_still_take_turns` pins
it. What is *missing* is not the mechanism but the telling:

1. **The page says so.** When another open session names the same port, the status strip
   says «этот клиент уже ведёт профиль X» rather than letting the second profile look
   independent.
2. **A new profile gets a free port by default.** `Workspace.open` offers the lowest port
   not claimed by an open session, so the accident is harder to have.
3. **The lease owner is named per profile.** `claim(owner)` currently passes `"panel"` /
   `"timer"`; it should pass `"<profile>/timer"`, so a refusal in the log says *which*
   profile is holding the game, not just that something is.

### 4.4 The in-process half of the claim

`GameLink` holds a local `threading.Lock` flag beside the daemon lease, because one
panel's buttons run on the Tk thread while its scheduler runs on its own. With several
sessions that flag is **per link**, which is right for two links on two ports and
redundant-but-harmless for two links on one port (the daemon refuses the second anyway).

There is one hole: if the daemon is unreachable, `_claim_lease` returns `True` — "nothing
else can be driving the game either", which was true with one panel process. With two
sessions in one process and one dead daemon, both would pass. The fix is small and
belongs in wave 3: **a process-wide registry of claims keyed by `(host, port)`**, taken
before the daemon is asked. Two links on one port then serialise even with no daemon.

### 4.5 Profiles whose client is in another Windows session

`tools/rdp_instance.py` already builds them, and #1204 taught the panel to recognise
them (`rdp_session` / `rdp_user`, and `game_process.profile_status` filtering by the
session's login instead of by executable name). For this task they are **the easy case**,
not the hard one: a different Windows session means a different desktop, so the two
clients never compete for the foreground, and the daemon is reachable over TCP exactly
like a local one.

Two things still owed:

* **Bringing one up from the panel.** Today `--bring-up` is a command line. A profile
  marked `rdp_session` should be able to start its session and its daemon from its own
  page. Wave 4, and it is a scenario plus a button, not new machinery.
* ~~**`launch_game.md` launches into THIS session.**~~ **Done (#1218)**, and it was a
  scenario change as predicted. `LAUNCH` — which always spawns on the desktop the panel
  is on — became `START_GAME`, whose route is picked by the profile: this desktop when
  it names no session, and `tools/session_launch.py` through the SYSTEM hop when it
  does. The session travels with the run as `Context.game_user`, beside the port and
  the lease, because the port cannot answer it: it reaches a client through the daemon
  *attached* to it, and a launch happens when there is nothing to be attached to. Both
  «Запустить игру» and the crash watchdog stopped refusing an RDP profile as a result.

  The *ending* half went the same way. `TerminateProcess` on another account's process
  really is refused for an unelevated panel — measured, `OpenProcess` returns error 5 —
  so `QUIT_GAME` retries through one elevated `taskkill /F /PID`. That is a smaller
  privilege than the start needs: getting a process INTO somebody else's session takes
  SYSTEM, getting one out takes an administrator.

* **The daemon was being started on the wrong desktop, and nobody had noticed.** Found
  while testing the above. `GameLink.ensure()` spawned `lua_daemon.py` as an ordinary
  child of the panel, so for an RDP profile it came up in the CONSOLE session, bound
  the profile's port (47655) and hijacked the console session's client —
  `find_game_pid` looks in the session the daemon itself runs in. Everything then
  worked and was wrong: the second profile's reads, its scenarios and its status all
  answered for the first account's game. Measured on the live box before the fix:
  port 47655's daemon in session 1, attached to pid 153576, the console client.

  So `GameLink` takes the session too and, when there is one, starts the daemon inside
  it through `rdp_instance.start_daemon`. And `game_client.target_pid` no longer
  believes a daemon whose attached pid is not in the profile's session — a wrong
  answer there is a fault to say out loud, not a fallback to use.

  Proof it is fixed: with both accounts up, the two daemons read two different games
  (<user2> 6 alliancemates waiting / 1664 wounded, the console account 0 / 241). Before,
  both readings were the console account's.

### 4.6 Foreground input — smaller than it looks

Last War ignores `PostMessage`; `CLICK` uses `inputs.click(..., mode="foreground")` and
`FIND` takes a screenshot of the window. Two clients cannot both be foreground on one
desktop. But measured rather than assumed:

* **0 of the 22 blessed scenarios** (`src/lastwar_bot/actions/*.md`) contain `FIND`,
  `CLICK`, `DRAG` or `TYPE`. Every one of them is headless Lua.
* 5 of the 12 `actions/dev/*.md` do, none of which a timer runs.
* The real foreground consumer is `tools/street_run_ai.py`, which is a child process and
  a deliberate one-at-a-time thing anyway.

So the foreground token of the original sketch is **not needed for wave 3** and would be
speculative machinery. What wave 3 owes instead is one honest guard: a scenario whose
parsed body contains a vision primitive takes a process-wide foreground lock before it
runs, and an RDP profile is exempt because its desktop is its own. Cheap, and it stays
correct if a vision scenario is ever blessed.

---

## 5. Timers and triggers

### 5.1 Already per profile — say why, because it matters

`Schedule` is built from `rt` and reads everything off it: the catalogues from
`rt.profiles.timers_json()` / `triggers_json()`, the last-run clock from
`timers_state()`, the gate from `game_process.profile_status(rt.settings)`, the runner
through `rt.actions` under `rt.game.claim()`, the listeners through `rt.children` (which
carry that profile's `LW_DAEMON_PORT` and lease). It is constructed lazily on first ask
and **started only by the shell**.

So N sessions is N schedules with N queues, and each already presses its own client. The
work is not to split it; the work is to start N of them and to make it visible whose is
which.

### 5.2 Starting and stopping

`ProfileSession.start()` calls `rt.schedule.start()` and is idempotent; `stop()` reverses
it; `Workspace.start_all()` fans out. Written, tested. What the shell owes is calling it
per session at the end of the boot rather than once.

Each schedule keeps its own single-file queue, so two errands of ONE profile still take
turns — which is the property that queue exists for — while two profiles run at once. Two
profiles that happen to share a client serialise at the lease (§4.3), and the loser's
errand is re-queued rather than failed.

### 5.3 Whose errand fired

Today a timer says `[timer] …`. With several schedules that is unreadable. Three changes,
all in the telling and none in the mechanism:

* the log line carries the profile — `[timer] main: collect_base_resources` — by giving
  `Schedule` the session's name for its tag, which is one argument;
* the technical log is already separated: each session past the first has its own
  debug-log scope, so `profiles/<name>/debug.log` is that profile's alone (wave 1);
* a page's log pane only ever shows its own session's lines, because the `LogBus` is the
  runtime's. Nothing is owed there — it falls out.

### 5.4 The trigger listeners

Each is a child process spawned by that session's `ChildFactory`, so it already sniffs
with the right `LW_DAEMON_PORT`. Two sessions therefore run two `wire_event_monitor.py`
children. That is correct and it is also **the main new cost**: N profiles × M enabled
triggers is N × M sniffer processes on one box. Worth measuring in wave 3's acceptance
rather than assuming; the mitigation, if it is needed, is that listeners watching the
same port for the same pattern could be shared — but not before there is a number saying
they must be.

---

## 6. The interface

### 6.1 The outer notebook

One `ttk.Notebook` above everything, one page per open profile, the profile's name on the
tab. **With a single session its tab strip is hidden** by a style whose `Tab` layout is
empty, so a one-profile panel looks exactly as it does now — no new chrome for the
operator who never wanted this.

Each page is what the window is today: the inner tab notebook, the log pane below the
sash, the status strip, the DSL line.

### 6.2 Opening and closing

The profile dialog (menu → «Профиль») grows two entries beside create / rename / delete:

* **«Открыть ещё профиль»** — pick one that is not open; it gets a page and starts. A
  profile already open is selected rather than opened twice.
* **«Закрыть профиль»** — shuts that session down (tabs, errands, claim, log files) and
  takes its page out. The last open profile cannot be closed; a window with none in it is
  a window with nothing in it.

Both already exist as `Workspace.open` / `.close`, and both already write down what is
open. The right-click menu on the outer notebook offers the same two.

**What is remembered:** `panel/settings.json` gained `open_profiles` beside
`active_profile` in wave 2a. A panel that has never had more than one profile open has no
such list, and then it opens exactly the profile the pointer names — every panel before
this, unchanged.

### 6.3 The tabs

Plugin tabs are built per window today. They become **per session**: each session builds
its own set, from its own profile's `tabs.enabled` / `tabs.order`. That is not extra work
— it is what already happens, run N times — and it is the honest answer to "which tabs
does this profile show", since the tab list is a profile setting.

It has a cost worth naming: two profiles with chat enabled open two chat stores and two
reader children. That is correct (two accounts have two chat histories) and it is the
same cost as running two panels, which is what the operator does today.

### 6.4 The log

**Per profile, on its page.** Not a merged view: the log is already the runtime's sink
with the widget on top, the coordinate links jump *this* profile's client, and the
producer filter is per pane. A merged all-profiles view is a nice idea and is explicitly
out of scope — it would need a second sink and a source column, and nobody has asked.

### 6.5 What the tab strip shows

The profile's name, and nothing decorative. A session that needs attention says so on its
own page (the status strip already does), and a badge on the tab is the kind of thing to
add after living with it.

---

## 7. What breaks — the inventory

Rated **done** (already fixed under this task), **low** (mechanical), **medium** (needs
thought), **high** (can silently misbehave).

### 7.1 The five process-globals — **done** (wave 1)

The lease in `os.environ`; the daemon port never reaching an in-process scenario; the
debug log's single handler; `ProfileManager` writing the panel-wide pointer; the
translator writing `~/.last_war_panel.json`. Each is described in §1 and each has a test.

### 7.2 The autostart's three per-profile artefacts — **medium**

#1203 landed while this was being written and it is the sharpest new collision. A panel
holds, **per profile**: a kernel lock on `profiles/<name>/panel.lock` (that lock IS the
answer to "is a panel on this profile"), a heartbeat `panel_alive.json` rewritten once a
minute from the Tk loop, and a scheduled task `Last War Bot\panel-<profile>` that opens
the panel if the heartbeat is stale.

With several profiles in one window all three become per session:

* the window must take **every open profile's lock**, and a profile whose lock is held by
  another panel must refuse to open (with a readable message) rather than open twice;
* the heartbeat must be written for every open session, or the hourly check will start a
  second panel on the profile this one is quietly farming;
* `--profile X` on the scheduled task must mean "open X **in the running panel** if one
  is up", not "start another panel". That is a new question #1203 could not have: the
  running panel is discoverable (it holds the locks), but there is no channel to ask it.
  Simplest honest answer for wave 4: the task's action stays "start a panel with X", the
  panel refuses because X's lock is held, and it says so in `autostart.log`. Anything
  better needs an IPC and is a separate task.

### 7.3 The shell's per-profile attributes — **high**

The 65 `self._x` on `Panel`, and the discipline of §3.4. High because a background
callback bound to the wrong session writes one profile's reading into another's strip and
nothing fails loudly. The classification is in §9 and the binding rule is one line; the
risk is in applying it by hand across 26 sites.

### 7.4 Autosave and the settings binder — **medium**

`_collect_settings` builds a fresh dict that REPLACES the profile, and `_install_autosave`
traces Tk variables. Both are per session once they are routed — but the Tk *variables*
are created by `SettingsBinder.create_vars(root)`, one set per runtime, so two runtimes in
one window means two `StringVar`s for the same knob on one interpreter. That is fine (Tk
names them uniquely) as long as nothing looks a variable up by name. Nothing does today; a
test should say so, because the failure mode is one profile's Settings page editing
another's.

### 7.5 i18n — **low**

The translator is already per runtime, and its widget registry holds weak references to
that session's widgets. The window's chrome is drawn in the showing session's language and
re-rendered on a page switch (§3.2). `tests/test_panel_i18n.py` keeps its teeth either
way. The eleven locale files are unaffected — the new strings are the ones in §6.2.

### 7.6 Child processes and captures — **low**

Every child goes through the session's `ChildFactory`, which already carries that
profile's port and lease (wave 1). Two sessions running the secret-task capture is two
capture children writing two checkpoints in two profile directories, which is right. The
only shared thing left is the machine: CPU, and npcap capture handles. §5.4's measurement
covers it.

### 7.7 «Стоп всё», the watchdog, and closing — **medium**

`_panic` currently stops everything there is. With several sessions the question is
*whose*, and the answer must be **all of them** — it is the emergency button. `_on_close`
likewise fans out. The watchdog is per session already (it reads
`profile_status(rt.settings)`, which #1204 taught to filter by Windows session), but it
must relaunch *its* client, and for an RDP profile that is §4.5's open item.

### 7.8 `python -m panel.tabs.<id>` — **low, and already improved**

A standalone tab is one profile in its own process and always was. Wave 1 made
`--profile alt` *pin* rather than move the panel-wide pointer, which was a real bug: the
next `python -m panel` came up on whatever profile the last standalone tab was given.
Nothing else is owed — the harness builds one runtime and one session's worth of state.

### 7.9 Geometry and the update check — **low**

Both are the window's. Geometry is currently saved into the profile (`window_geometry`);
with several profiles that becomes "whichever page was showing when you closed", which is
wrong but harmless. Move it to `panel/settings.json` in wave 4 — it is a window fact, not
a profile fact. The update check runs once for the checkout, not once per profile.

### 7.10 Not in the way, worth saying

`tools/lib/game_lease.py`, `tools/lua_daemon.py`, `tools/rdp_instance.py`,
`panel/childmon.py`, `panel/widgets.py`, `panel/splash.py`, and every module under
`panel/tabs/` need no change at all. The last is the load-bearing surprise, and it is
what the previous refactor bought.

---

## 8. Waves

Each is a commit that leaves the panel working, each has a check to run before the next
starts. Sizes are honest estimates of *new and changed* lines.

| # | Wave | Size | Risk | State |
|---|---|---|---|---|
| 1 | Runtime isolation: the five globals of §7.1, plus tests | ≈300 + 480 test | low | **done** `c7e65db` |
| 2a | `ProfileSession`, `Workspace`, `SessionScoped`, `open_profiles` | ≈370 + 370 test | low | **done** `1d0da8d` |
| 2b | The shell holds the workspace: a page per session, the outer notebook, the boot per session | ≈400 changed in `__main__.py` | **high** | to do |
| 3 | Parallel operation: the per-port claim registry, named lease owners, per-profile timer tags, the foreground guard, «Стоп всё» and close fanning out | ≈200 | medium | to do |
| 4 | Open / close from the UI, the autostart's three artefacts per session, geometry to the window file, strings in all eleven locales | ≈300 | medium | to do |

### Wave 1 — runtime isolation. **Done.**

Nothing a single-profile operator can see changes, except that a profile on a non-default
port finally presses its scenarios into its own client.
*Accepted:* `tests/test_panel_multi_profile.py` 18/18; the whole suite has no new red.

### Wave 2a — the objects. **Done.**

`ProfileSession`, `Workspace`, `SessionScoped`, and `open_profiles` in the panel-wide
file. No shell change.
*Accepted:* `tests/test_panel_workspace.py` 20/20, with no display.

### Wave 2b — the shell. **The expensive one; do it alone.**

`Panel` becomes `SessionScoped`, builds a `Workspace`, restores what was open, gives each
session a page, and boots them in parallel. `__init__` splits into the window's half and
`_open_session_page(session)`. The binding discipline of §3.4 is applied at all 26
scheduling sites.

*Accept:*
1. a panel with one profile is **indistinguishable** from today — same look, same (hidden)
   tab strip, same log, same boot time, same `debug.log` path;
2. two profiles on two ports both come up warm, and each page's status strip names its own
   client;
3. a timer of the hidden profile fires and its line appears in **that** profile's pane and
   `panel.log`, not the showing one's;
4. switching pages while an errand runs neither stops it nor moves its output;
5. the contract test and `test_panel_leaks.py` stay green.

### Wave 3 — parallel operation.

The `(host, port)` claim registry (§4.4); `claim("<profile>/timer")` so a refusal names
who holds the game; the timer tag carrying the profile; the foreground guard (§4.6);
`_panic` and `_on_close` fanning out; and a measurement of what N sessions cost in
processes and CPU (§5.4).

*Accept:* two profiles deliberately given the SAME port — the second's errands are refused
with a line naming the first, are re-queued, and run once the first lets go; neither
profile ever presses while the other holds; «Стоп всё» stops both.

### Wave 4 — the UI and what is remembered.

«Открыть ещё профиль» / «Закрыть профиль» in the profile dialog and on the notebook's
context menu; a free daemon port offered to a newly opened profile (§4.3); the autostart's
lock, heartbeat and scheduled task per open session (§7.2); geometry moved to
`panel/settings.json`; every new string in all eleven locale files in the same commit.

*Accept:* open a second profile from the menu, close the panel, reopen — both come back
with the same page on screen; a profile whose lock another panel holds is refused with a
readable message; `tests/test_panel_i18n.py` green (it fails on a key missing from any
shipped locale and on a translatable literal handed to a widget).

---

## 9. Wave 2b, itemised

Written out because the shell is edited by several tasks at once and this must be picked
up mid-flight without re-deriving it.

### 9.1 The attribute classification

From the 65 `self._x =` assignments in `panel/__main__.py`:

**Per profile — declare in `SESSION_ATTRS`.** The runtime and its pieces (`_rt`,
`_profiles`, `_binder`, `_i18n`, `_logbus`, `_tick`, `_children`, `_game`, `_actions`,
`_schedule`, `_timers`, `_triggers`, `_timer_store`); the technical loggers (`_dbg`,
`_dbg_ui`, `_dbg_status_prev`); the log pane (`_log`, `_log_lines`, `_log_kept`,
`_log_menu`, `_log_filter_var`); the tab area (`_main_nb`, `_main_split`,
`_main_controls`, `_lazy_tabs`, `_plugin_tabs`, `_shown_tab`); the two strips
(`_status_var`, `_status_lbl`, `_status_msg`, `_status_busy`, `_daemon_var`,
`_daemon_lbl`); the account summary (`_dash_values`, `_dash_stop`, `_dash_err`,
`_dash_view`); the map sweep (`_sweep_stop`, `_sweep_at`, `_sweep_pass`); the liveness
counters (`_game_gone`, `_game_was_up`, `_watchdog_last`); the command line (`_cmd_var`,
`_cmd_at`).

**The window's — leave alone.** `_splash`, `_boot_step`, `_boot_done`; `_profile_var`,
`_profile_combo`, `_profile_win`; `_senddiag_win`; `_lang_var`; `_resize_job`,
`_resize_size`, `_paint_hwnd`, `_paint_off`; every `_update_*`; `_health_prev`.

**Neither — they are properties** and must NOT be declared: `_settings`, `_loading`,
`_opt_vars`, `_game_status`, `_daemon_up`, `_client`, `_busy`, and the read-only
shorthands. `SessionScoped` refuses to route a descriptor, so a mistake there is inert —
but do not make it.

### 9.2 The three binding helpers

```python
@contextmanager
def _on(self, session):        # swap the showing session for the duration
def _bound(self, func):        # func, re-entering the session it was made in
def _later(self, ms, func):    # self.after, bound
```

`_arm()` binds what it arms. The 26 sites are exactly
`grep -n 'self\.after(\|threading\.Thread(\|self\._arm(' panel/__main__.py`.
`_on` is safe to swap because every Tk callback runs on one thread.

### 9.3 The window

* one outer `ttk.Notebook`, tab strip hidden by an empty `Tab` layout while there is one
  session;
* `__init__` splits into the window's half and `_open_session_page(session)`, the latter
  run once per session under `_on(session)`;
* `_startup_boot`, `_refresh_status`, `_panic` and `_on_close` fan out through
  `workspace.each()`;
* `_switch_profile` keeps working for a window with one page (it re-points that session);
  with several, switching means bringing another page to the front.

---

## 10. Testing

* **`tests/test_panel_multi_profile.py`** (written) — the five globals, and that two links
  on one port take turns.
* **`tests/test_panel_workspace.py`** (written) — the workspace, and the attribute
  routing, with no display.
* **A two-session shell test** (wave 2b) — build the window against two scratch profiles
  with cold game links; assert that each page's widgets belong to its own session, that a
  callback armed on the hidden session writes into the hidden session, and that switching
  pages starts and stops nothing.
* **A same-port test** (wave 3) — two sessions, one port, one daemon: the second claim is
  refused, the errand is re-queued, and it runs once the first releases.
* **The existing gates** — `test_panel_tab_contract.py` (every tab still builds cold),
  `test_panel_i18n.py` (no key missing from any of the eleven locales, no literal handed to
  a widget), `test_panel_leaks.py`.

`tests/*.py` here are self-running scripts under Windows Python; the new ones follow that
shape. Two files are red for reasons that predate this work and must not be read as
regressions: `test_street_run_stepdown.py` (one case, since #1166) and
`test_panel_debug_log.py` (Windows only — the test closes its handler after the temp
directory is removed).

---

## 11. Decisions taken, so they can be argued with

* **The whole runtime is per profile**, not a shared frame with light sessions. There is
  nothing genuinely shared left in it, and §1 is the record of what happens when something
  pretends to be.
* **A hidden page keeps running.** Anything else makes "two accounts at once" a lie.
* **The log is per profile, on its page.** A merged view would need a second sink and a
  source column; nobody has asked, and the coordinate links belong to one client.
* **The daemon outlives the closed profile.** It is the client's, not the window's, and it
  deliberately survives the panel today.
* **Two profiles on one port are allowed and take turns**, rather than being forbidden.
  Forbidding would need a registry of ports across panels; taking turns is what the lease
  already does, and the second profile is honest about being second.
* **No foreground token in wave 3.** None of the 22 blessed scenarios needs the window; a
  guard for the day one does, and nothing more.
* **The tab list stays a profile setting**, so each session builds its own tabs. Two chats
  mean two stores, which is what two accounts are.
* **Geometry becomes a window setting.** It is the window's fact; keeping it per profile
  means the last page showing decides, which is arbitrary.
* **No IPC into the running panel** for the autostart's `--profile X` (§7.2). The panel
  refuses and says why; a channel into a running panel is its own task, with its own
  security question.
