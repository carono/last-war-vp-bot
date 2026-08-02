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
necessary — the names already say "this profile's". Instead:

* `panel/runtime/session.py` holds `ProfileSession` — the runtime, the lifecycle, and a
  `state` dict for whatever the shell keeps per profile;
* `SessionScoped` (same module) routes a DECLARED set of attribute names to the session
  whose page is showing; `Panel` declares that set;
* the lifecycle calls that must reach *every* session go through `workspace.each()`.

Both are written and tested (`tests/test_panel_workspace.py`). What remains is the
wiring, itemised in §7.

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

| # | What lands | State |
|---|---|---|
| 1 | Runtime isolation: the five globals above, and tests that two runtimes in one process do not touch each other | **done** — `c7e65db` |
| 2a | `ProfileSession`, `Workspace`, `SessionScoped`, `open_profiles` in the panel-wide file | **done** — `1d0da8d` |
| 2b | The shell holds the workspace: a page per session, the outer notebook, the boot per session | §7 |
| 3 | Parallel operation: per-port claims, the foreground token, per-session watchdog | §4 |
| 4 | Opening and closing a profile from the UI, and every string in every locale | §7.4 |

Each wave is a commit that leaves the panel working with one profile. Waves 1 and 2a
change nothing a single-profile operator can see, except that a profile on a non-default
port finally presses its scenarios into its own client.

## 7. Wave 2b, itemised

The design questions are settled; what is below is the work. It is written out because
the shell is edited by several tasks at once and this must be picked up mid-flight
without re-deriving any of it.

### 7.1 `Panel` becomes session-scoped

`class Panel(runtime.SessionScoped, tk.Tk)` with `SESSION_ATTRS` naming exactly the
per-profile attributes. The classification, from the 65 `self._x =` assignments in the
file:

**Per-profile — declare these.** The runtime and its pieces (`_rt`, `_profiles`,
`_binder`, `_i18n`, `_logbus`, `_tick`, `_children`, `_game`, `_actions`, `_schedule`,
`_timers`, `_triggers`, `_timer_store`); the technical loggers (`_dbg`, `_dbg_ui`,
`_dbg_status_prev`); the log pane (`_log`, `_log_lines`, `_log_kept`, `_log_menu`,
`_log_filter_var`); the tab area (`_main_nb`, `_main_split`, `_main_controls`,
`_lazy_tabs`, `_plugin_tabs`, `_shown_tab`); the two strips (`_status_var`,
`_status_lbl`, `_status_msg`, `_status_busy`, `_daemon_var`, `_daemon_lbl`); the account
summary (`_dash_values`, `_dash_stop`, `_dash_err`, `_dash_view`); the map sweep
(`_sweep_stop`, `_sweep_at`, `_sweep_pass`); the liveness counters (`_game_gone`,
`_game_was_up`, `_watchdog_last`); the command line (`_cmd_var`, `_cmd_at`).

**The window's — leave these alone.** The splash and boot (`_splash`, `_boot_step`,
`_boot_done`); the profile modal (`_profile_var`, `_profile_combo`, `_profile_win`); the
diagnostics dialog (`_senddiag_win`); the language menu variable (`_lang_var`); geometry
and painting (`_resize_job`, `_resize_size`, `_paint_hwnd`, `_paint_off`); the update
block (every `_update_*` — one checkout, one answer); `_health_prev`.

**Neither — they are properties already** and must NOT be declared: `_settings`,
`_loading`, `_opt_vars`, `_game_status`, `_daemon_up`, `_client`, `_busy`, and the rest
of the read-only shorthands. `SessionScoped` refuses to route a name that is a
descriptor, so a mistake here is inert — but do not make it.

### 7.2 Binding background work to its session

This is the part that is easy to get wrong. Routing answers "the session whose page is
showing", which is right for a button and wrong for a timer that fires while the
operator is looking at another profile.

**Bind at the SCHEDULING site, not at the use site.** Three helpers on `Panel`:

```python
@contextmanager
def _on(self, session):        # swap the showing session for the duration
def _bound(self, func):        # func, wrapped to re-enter the session it was made in
def _later(self, ms, func):    # self.after, bound
```

and then, mechanically, in `panel/__main__.py`: `_arm()` binds what it arms (one change,
covers every timer loop — the log pump, the status poll, the health snapshot, the update
poll); each of the ten `threading.Thread(target=…)` targets is wrapped in `_bound`; each
of the ten `self.after(…)` calls whose callback touches a declared name becomes
`_later`. All twenty-six sites are listed by `grep -n 'self\.after(\|threading\.Thread(\|self\._arm('`.

`_on` is safe to swap because every Tk callback runs on one thread. A worker thread must
NOT touch a declared name directly — it computes and hops back with `_later`. One place
does today: `_dash_loop` calls `_dash_tick` off the Tk thread. Give the loop its session
explicitly.

**The plugin tabs need none of this.** A tab holds its own `rt` and never reads a shell
attribute, so a tab of a hidden profile is already correct. That is the tabs-are-plugins
rule paying for itself.

### 7.3 The window

* One outer `ttk.Notebook`, always present. With a single session its tab strip is
  hidden by a style whose `Tab` layout is empty, so a one-profile panel looks exactly
  as it does now.
* `__init__` splits in two: the window's own half (title, geometry, splash, menu,
  exception logging, updates, resize damper) and `_open_session_page(session)` — which
  is everything else, run once per session with `_on(session)` held.
* `_startup_boot`, `_refresh_status`, `_panic` and `_on_close` fan out with
  `workspace.each()`.
* `_switch_profile` keeps working for a window with one page (it re-points that
  session); with several, switching means bringing another page to the front.

### 7.4 Opening and closing, and the strings

The profile modal grows «Открыть ещё профиль» and «Закрыть профиль», and the outer
notebook's context menu offers the same two. `Workspace.open` / `.close` already do the
work and already remember it.

New locale keys go into **every** file in `panel/locales/` in the same commit — read the
directory for the list; it has doubled twice while this task was open. At the time of
writing: `de en es fr id it pl pt ru tr vi`.

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
