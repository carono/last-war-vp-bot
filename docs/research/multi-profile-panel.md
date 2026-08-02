# Several profiles open at once, in one window

Task #1206. Today one panel means one profile, one daemon, one client. Farming two
accounts means two panels, two windows, two logs — and on the same machine the second
one quietly drives the first one's client, because half of what says *which* game to
press lives in the process rather than in the profile.

This is the plan for making a profile a **session**: a thing the window can hold several
of, each with its own daemon, its own schedule, its own tabs, its own log, running at the
same time and out of each other's way.

## 1. Where we already are

Most of the work was done by the tabs refactor and never used for this. It is worth
stating plainly, because it decides how much of the panel has to change:

* **`PanelRuntime` is already per-profile, not per-process.** It owns the profile
  manager, the settings binder, the translator, the log sink, the ticker, the child
  factory, the game link, the action runner and the schedule (`panel/runtime/host.py`).
  Nothing about it says "the one".
* **A tab already talks to nothing but its runtime.** That is the binding rule in
  `CLAUDE.md`, and the contract test enforces it.
* **A second runtime is already built today.** `panel/tabs/base.run_tab` — what
  `python -m panel.tabs.rally` runs — constructs a whole second `PanelRuntime` around a
  bare root, and `host.standalone()` even re-points it at another daemon port.

So the object model is right. What is missing is that a handful of facts about "which
game am I driving" are held in the **process** instead of in the runtime, and that the
shell (`panel/__main__.py`) is written as though there were exactly one of everything.

## 2. The five process-globals

These are the whole of wave 1. Each is small; together they are the reason two runtimes
in one process press the wrong client.

### 2.1 The game lease lives in `os.environ`

`GameLink._claim_lease` writes the daemon's lease token to `os.environ["LW_GAME_LEASE"]`
and `release()` pops it (`panel/runtime/daemon.py`). One environment, N sessions:

* session B claiming overwrites session A's token, and A's next chunk is refused as a
  lost lease;
* session A releasing pops B's live token, and B's children run unleased;
* a child spawned by A inherits whatever token was in the environment at that instant.

**Fix.** The token belongs to the link that holds it: `GameLink._token`, handed to every
client and evaluator it builds, and handed to `ChildFactory.env()` for the children. The
environment variable stays what it always was for a *standalone tool* — how a process
started from a shell inherits a lease — and stops being how the panel talks to itself.

### 2.2 The daemon port never reaches a scenario

`script_engine._evaluator()` calls `lua_client.get_evaluator()` with no port, and
`lua_client.PORT` is read from the environment **at import**. So every scenario the panel
runs in-process goes to 47654, whatever the profile says.

This is a live bug today, with one profile: a profile pointed at 47655 drives the second
Windows session's client from its captures and its children (they get `LW_DAEMON_PORT`
from `ChildFactory.env()`) but presses its *scenarios* — which is most of what the panel
does — into the console session's client. It is also an absolute blocker for two
sessions, so it is fixed here rather than filed separately.

**Fix.** A run target travels on the context: `Context.game_port` and `Context.game_token`,
threaded through `new_context` / `run_action` / `run_text`, used by `_evaluator()`.
`ActionRunner` is given the runtime's target and passes it on every call. `get_evaluator`
grows a `token` argument so a context-built evaluator carries its own lease.

### 2.3 The debug log is one file for the whole process

`panel/debug_log.py` puts one rotating handler on one logger tree, and `configure()`
re-points it. Two sessions mean both profiles' lines land in whichever profile called
`configure()` last — and the other profile's `debug.log` stops growing, which is the
worst possible failure for a diagnostic.

**Fix.** A **scope** in the logger name: the handler sits on `lastwar.panel.<scope>` and
a component logger is `lastwar.panel.<scope>.<component>`. `configure(path, scope=…)`
and `get_logger(component, scope=…)`. An unscoped call keeps meaning exactly what it
means now, so nothing that has not been migrated changes behaviour. The runtime grows
`rt.dbg(component)`, and the three modules holding a module-level `_dbg`
(`dashboard`, `timers`, `triggers`) take theirs from the runtime instead.

### 2.4 `ProfileManager` moves a panel-wide pointer

`set_active()` writes `active_profile` into `panel/settings.json`. A session must be able
to *be* a profile without claiming to be the panel's current one.

**Fix.** `ProfileManager(pin=name)`: pinned, `_active` is that name and `set_active` does
not touch the shared file. The panel-wide memory becomes a list — which profiles were
open, and which one was on screen — written by the workspace, not by a session.

### 2.5 The language preference is a file in `$HOME`

`Translator._save_pref` writes `~/.last_war_panel.json` on every `set_lang`. With two
sessions the last one to be built wins, and the losing profile silently changes language.

**Fix.** The per-profile language is already in the profile's `config.json`; the global
pref is only the fallback for a runtime that has no profile. A session-scoped translator
is built with `persist=False`.

## 3. The shape of the window

A **session** is one open profile: its runtime, its schedule, its monitors, its tabs, its
log pane, its status strip. A **workspace** is the set of sessions one window holds, plus
which of them is on screen.

```
Panel (tk.Tk)                     the window: menu, geometry, updates, «о программе»
└── outer notebook                one page per OPEN PROFILE
    ├── «main»  → ProfileSession  runtime · tabs notebook · log pane · status strip
    └── «alt»   → ProfileSession  its own of each, its own daemon on its own port
```

Everything that runs while nobody is looking — the schedule, the trigger listeners, the
captures, the dashboard poller — belongs to the **session**, so a profile whose page is
not on screen keeps farming. Only the drawing follows the notebook.

### How the shell gets there without being rewritten

`panel/__main__.py` is 2 900 lines of methods written against `self._rt`, `self._log`,
`self._game`, `self._dash_values`… Rewriting every one of them is neither safe nor
necessary. Instead:

* `panel/runtime/session.py` holds `ProfileSession` — the runtime plus every per-profile
  attribute the shell keeps today;
* `Panel` declares `SESSION_ATTRS`, the explicit, tested list of attribute names that
  belong to a session rather than to the window, and routes reads and writes of exactly
  those names to the session currently on screen;
* the lifecycle methods that must run for *every* session (boot, status poll, panic,
  close) are called through `workspace.each()` instead of once.

The routing is deliberately narrow and named: a test builds two sessions and asserts that
setting one of those attributes on one session leaves the other's untouched, and a second
test asserts that no *other* attribute of the shell is per-profile.

## 4. What "not in each other's way" actually requires

Three collisions are real, and none of them is solved by having two runtimes.

**Two sessions on the same daemon port are the same client.** They must take turns. The
daemon's lease already does this between processes; in-process, two `GameLink`s on one
port must share a claim, so the registry of claims is keyed by port rather than kept per
link. The profile page says so plainly rather than letting the second profile look
independent.

**A scenario that needs the window focused cannot run for two clients at once** — not in
one Windows desktop. Last War ignores `PostMessage`; the vision-and-keystroke primitives
need the client foreground. Headless Lua does not, and by now most abilities are Lua. So:
a process-wide *foreground token*, taken only by a run whose parsed script actually
contains a vision primitive, and a client in its own Windows session (an RDP profile,
`tools/rdp_instance.py`) exempt from it because its desktop is its own.

**The watchdog must relaunch its own client.** Finding the client by executable name
alone finds the console session's one for every profile. Task #1204 is adding the session
filter to `panel/runtime/game_process.py`; this work depends on it and must not duplicate
it.

## 5. Waves

| # | What lands | Files |
|---|---|---|
| 1 | Runtime isolation: the five globals above, plus tests that two runtimes in one process do not touch each other | `runtime/daemon.py`, `runtime/children.py`, `runtime/host.py`, `script_engine.py`, `lua_client.py`, `debug_log.py`, `i18n.py`, `profile.py` |
| 2 | `ProfileSession` + `Workspace`, the outer notebook, the shell's attribute routing | new `runtime/session.py`, `runtime/workspace.py`, `__main__.py` |
| 3 | Parallel operation: per-port claims, the foreground token, per-session schedule start/stop, per-session watchdog | `runtime/daemon.py`, `runtime/schedule.py`, `script_engine.py` |
| 4 | Opening and closing a profile from the UI, what is remembered, every string in all five locales | `__main__.py`, `panel/settings.json`, `panel/locales/*.json` |

Each wave is a commit that leaves the panel working with one profile — wave 1 in
particular changes no behaviour a single-profile user can see, except that a profile on a
non-default port finally presses its scenarios into its own client.

## 6. Notes for whoever picks this up

* The locale set is the CONTENTS of `panel/locales/`, not the three names `CLAUDE.md`
  happens to list — it went from three to ten while this plan was being written. Read
  the directory every time.
* `panel/runtime/diag.py` still asks `debug_log.get_logger("sender")` directly, so a
  diagnostic hand-off is written into the shared file whichever profile asked for it.
  Harmless (it names the archive it made) and left for whoever needs it scoped.
* Two waves' worth of the shell (`panel/__main__.py`) were being rewritten by other
  tasks alongside this one (#1203 autostart, #1204 RDP sessions, #1205 forced restart).
  Additive edits only, and stage by hunk, never the whole file.
