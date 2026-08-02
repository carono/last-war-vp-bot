# Panel tabs as self-contained runnable modules

A design document. Plan only — no code is written by this task.

The goal: every tab of the control panel is a module that can be run on its own —

```
C:\Python312\python.exe -m panel.tabs.rally --profile main
```

— and opens a working window with just that tab in it, where everything works:
the reads off the live game, the buttons, the settings saved back to the profile.
The panel itself becomes a **shell** that plugs tabs in as plugins, and *which*
tabs are plugged in is named by the active profile.

Read against `panel/__main__.py`, `panel/tabs_extra.py`, `panel/secret_tasks.py`,
`panel/command_post.py`, `panel/profile.py`, `panel/timers.py`,
`panel/triggers.py`, `panel/i18n.py`.

---

## 1. Why, in numbers

`panel/__main__.py` is ≈7 600 lines and `Panel(tk.Tk)` is two things at once: the
application window *and* the runtime every tab leans on.

| Subject inside `__main__.py` | ≈ lines |
|---|---|
| boot, settings collect/apply, menu, profile dialogs | 1 360 |
| chat tab (views, DM, emoji picker, store, child) | 1 050 |
| timers + triggers tab (grid, editor dialog, catalogue) | 800 |
| secret-task capture + auto-loot + map sweep + ghost order | 650 |
| scenarios tab (list, editor, runner, loop) | 480 |
| log (bus, mirror, severity, filter, retention, links) | 450 |
| Develop-menu sniffers (traffic + Lua tracer, run notes) | 450 |
| rally (monitor, alert, auto-join, daily caps, settings page) | 460 |
| settings page (three sub-pages, knob rows) | 400 |
| daemon, children, status, watchdog | 350 |
| geometry/resize, dashboard strip, jump/act, stats | 450 |

The three tabs that *were* extracted are classes taking `(app, parent)` that reach
back into the app by private attribute. Counted across `tabs_extra.py`,
`secret_tasks.py` and `command_post.py`: **`app._tr` 82 times, `app._t` 48**, plus
`app._daemon_port`, `app._profiles`, `app._log_put`, `app._arm`, `app._child`,
`app._say`, `app._python`, `app._jump`, `app._claim_busy`,
`app._read_resource_balance`.

Four costs follow:

1. **A tab cannot be run, tested or demoed on its own.** One change to the rally
   form means booting the whole panel: daemon, monitors, chat store, schedule.
2. **A tab that raises during build kills the boot.** `_build_ui` is one straight
   line of fourteen constructions.
3. **Every lifecycle event is a hand-written list.** `_sync_monitors`, `_panic`,
   `_on_close` and `_apply_language` each name the subsystems one by one, and a new
   tab means remembering all four.
4. **Nothing can be switched off.** An operator who never uses chat still pays for
   its subprocess, its SQLite store and its image cache.

The tests already show the answer's shape: `tests/test_panel_tabs_extra.py` and
`tests/test_panel_rally_tab.py` each hand-roll a minimal `_App` stand-in with `_t`,
`_tr`, `_daemon_port`, `_daemon_up`, `_read_resource_balance`. That ad-hoc fake
**is** the interface — this plan writes it down and makes it real.

---

## 2. Target shape

```
panel/
  __main__.py          the shell: window, notebook, menu, log pane, status strip
  runtime/
    __init__.py        PanelRuntime — assembled by the shell OR by a standalone tab
    i18n.py            Translator: t(), tr() weak registry, hook(), set_lang()
    log.py             LogBus — the sink: tags, severity, panel.log + debug.log
                       mirrors, stdout. The widget is the shell's (§4.4).
    settings.py        SettingsBinder: profile-scoped values, autosave, per-tab blocks
    daemon.py          GameLink: evaluator, port, ensure/restart, the one-action lock
    actions.py         ActionRunner: run_action / run_text / resolve / parse
    children.py        child-process factory (panel/childmon.py stays the monitor)
    tick.py            arm/disarm named repeating callbacks, on_tk()
    schedule.py        TimerScheduler + TriggerWatcher wiring (runtime half of Timers)
    bus.py             tiny publish/subscribe for cross-tab facts
    captures.py        CAPTURE_OPTIONS and friends (no longer stashed on the app)
  tabs/
    __init__.py        the registry: id -> module:class, order, default-enabled
    base.py            PanelTab (the contract) + run_tab() (the standalone harness)
    __main__.py        `python -m panel.tabs --list`
    alliance.py  profile.py  inventory.py  heroes.py  accounts.py  stats.py
    rally/  secret_tasks/  command_post/  scenarios.py  timers/  chat/  develop.py
  profile.py  widgets.py  splash.py  debug_log.py  childmon.py  … (unchanged)
```

Two rules make the split hold:

* **A tab imports from `panel.runtime` and `panel.widgets`, never from
  `panel.__main__`.** Not style — `python -m panel` executes `__main__.py` *as*
  `__main__`, so `from . import __main__` inside a tab re-executes the whole file as
  a second module. That is exactly why `CAPTURE_OPTIONS` is stashed on the instance
  today (`self.capture_options`); once it lives in `panel/runtime/captures.py` the
  workaround goes.
* **A tab may be absent.** Anything reaching another tab goes through
  `rt.tabs.get("<id>")` and tolerates `None`, or through the bus. The panel already
  does this by accident (`getattr(self, "_secret_tasks_tab", None)`); the plan makes
  it the contract.

---

## 3. The tab contract

What a tab **declares about itself** — everything the container and the standalone
harness need to know without importing anything else:

```python
class PanelTab:
    """One tab. Built into a frame; knows nothing about the notebook around it."""

    # -- identity ----------------------------------------------------------
    ID: str                          # "rally" — key in the profile, and the CLI name
    TITLE_KEY: str                   # "tab.rally"
    ORDER: int = 100                 # default position in the notebook
    DEFAULT_ENABLED: bool = True     # is it in a fresh profile's tab list
    PREFERRED_SIZE: str = "760x600"  # standalone window default

    # -- what it owns ------------------------------------------------------
    LOCALE_NS: tuple[str, ...] = ()  # locale prefixes it owns ("rally_tab", "rally")
    SETTINGS: dict = {}              # key -> default, stored in the profile's tab block
    LEGACY_KEYS: dict = {}           # new key -> old flat key in config.json (§5)
    TIMERS: tuple[TimerSpec, ...] = ()      # scheduled errands it contributes (§3.2)
    TRIGGERS: tuple[TriggerSpec, ...] = ()  # wire-driven errands it contributes
    NEEDS: frozenset = frozenset()   # "daemon" | "children" | "schedule" | "actions"
                                     # | "chat_store" — what the runtime must bring up

    def __init__(self, rt: PanelRuntime, parent: ttk.Frame) -> None: ...

    # -- construction ------------------------------------------------------
    def build(self) -> None: ...            # widgets only; must not touch the game
    SETTINGS_PAGE_KEY: str = ""             # "settings.tab.autorally", if it has one
    def settings_page(self, parent) -> None: ...   # the page it contributes (§6)

    # -- lifecycle ---------------------------------------------------------
    def ensure_loaded(self) -> None: ...    # first time shown — the lazy data read
    def on_show(self) -> None: ...          # the notebook selected it
    def on_hide(self) -> None: ...          # the notebook left it
    def on_profile_switch(self) -> None: ...# re-point per-profile state, bounce children
    def on_language_change(self) -> None: ...# only if tr() is not enough
    def panic(self) -> None: ...            # what «Стоп всё» must stop here
    def shutdown(self) -> None: ...         # the window is closing

    # -- persistence -------------------------------------------------------
    def config(self) -> dict: ...           # what to write into the profile
    def apply_config(self, raw: dict) -> None: ...
    def persist_vars(self) -> list: ...     # vars whose change means "save now"
```

Every method has a no-op default, so a read-only tab implements `build`, `fetch`,
`render` and nothing else — exactly what `tabs_extra._DataTab` already does. That
class survives as `panel/tabs/_data.py`, re-parented onto `PanelTab`.

### 3.1 The one hard rule of `build()`

**`build()` must not touch the game.** A standalone tab has to open with no daemon,
no client and no network. Everything live goes in `ensure_loaded()`. This is already
the de-facto rule in `tabs_extra.py`; it becomes *enforceable* because the standalone
harness builds every tab against a runtime whose `GameLink` is cold, and the contract
test (§11) asserts no evaluator was requested during build.

### 3.2 Timers and triggers a tab brings with it

Today the timer and trigger catalogues are two flat template files
(`panel/timers.json`, `panel/triggers.json`), copied into each profile, and the
Timers tab shows all of them regardless of which tab the errand belongs to. Three of
the triggers are not errands at all but panel-internal hooks with sentinel scenario
names — `__inventory_refresh__`, `__leaderboard_collect__`, `__secret_task_share__`
— each dispatched by an `if` inside the runner.

Under the plugin model a tab **contributes** its entries:

```python
class SecretTasksTab(PanelTab):
    TRIGGERS = (
        TriggerSpec(name="secret_task_share", event="alliance.share.mission.add",
                    handler="on_shared_task"),      # a method on THIS tab, not a sentinel
    )

class InventoryTab(PanelTab):
    TRIGGERS = (TriggerSpec(name="inventory_refresh",
                            event="push.resource.item.update", handler="refresh"),)
```

Rules:

* A spec whose `scenario` names an `actions/*.md` stays data and is handled by
  `runtime/schedule.py` exactly as today.
* A spec with a `handler` replaces the three sentinels: the watcher calls the named
  method on the owning tab, and **if that tab is not enabled the trigger is not
  offered at all** — which is the correct behaviour and today's `if` chain cannot
  express it.
* The *profile's* `timers.json` / `triggers.json` stay the source of truth for what is
  switched on and how often; a contributed spec is only the **template entry**, merged
  into a profile that has never seen it — the same seeding rule the template files
  already have. Nothing in an existing profile is rewritten.
* The Timers tab groups rows by contributing tab; rows belonging to a disabled tab are
  hidden, never deleted — disabling a tab must not silently drop its schedule.

### 3.3 What the shell does with a tab

```python
spec = registry["rally"]
tab  = spec.load()(rt, frame)      # import is lazy and wrapped in try/except
tab.build()
rt.settings.bind_tab(tab)          # SETTINGS + persist_vars() + autosave traces
tab.apply_config(rt.settings.tab_config(tab.ID))
rt.schedule.register(tab)          # TIMERS + TRIGGERS
# …later, on first show:
tab.ensure_loaded()
```

`run_tab` performs the very same sequence. That is the point: standalone is not a
second implementation that rots, it is the same six lines minus the notebook.

---

## 4. The shared runtime

### 4.1 What moves into it

| Today (`Panel` member) | New home |
|---|---|
| `_i18n`, `_t`, `_tr`, `_hook`, `_tr_widgets`, `_sweep_tr_widgets`, `_apply_language`, `_set_language` | `runtime/i18n.py::Translator` |
| `_log_q`, `_log_put`, `_say`, `_pump_log`, `_append_log`, `_open/_close_panel_log`, `_log_tag`, `_log_severity`, `_log_cap`, `_trim_log` | `runtime/log.py::LogBus` (no Tk) |
| `_log`, `_insert_line`, `_redraw_log`, `_clear_log`, `_install_log_copy`, coord/photo links | **shell** — the «Главная» tab's `LogView` (§4.4) |
| `_profiles`, `_settings`, `_opt_vars`, `_opt*`, `_collect_settings`, `_apply_settings_to_ui`, `_install_autosave`, `_loading`, `_save_settings` | `runtime/settings.py::SettingsBinder` |
| `_client`, `_daemon_port`, `_daemon_up`, `_ensure_daemon`, `_restart_daemon`, `_rebind_daemon`, `_current_server`, `_act`, `_claim_busy`, `_release_busy`, `_jump` | `runtime/daemon.py::GameLink` |
| the six `from lastwar_bot import script_engine` sites (`_run_command`, `_run_md_action`, `_load_scenario_into_editor`, `_scenario_problem`, `_run_timer_action`) | `runtime/actions.py::ActionRunner` |
| `_child`, `_child_env`, `_python` | `runtime/children.py` |
| `_arm`, `_disarm`, `_disarm_all`, `_on_tk`, `_loops` | `runtime/tick.py` |
| `_timers`, `_triggers`, catalogue load/save, `_run_timer_action`, `_timer_gate`, `_errand_args`, `submit` | `runtime/schedule.py` |
| `_configure_debug_log`, `_dbg*`, `_install_exception_logging` | `runtime/__init__.py` + existing `panel/debug_log.py` |
| `_refresh_status`, `_poll_status`, `_watchdog_check`, `_launch_game`, `_restart_game` | shell, exposed as `rt.game.status()` |
| `_build_menu`, `_show_about`, `_open_send_log_dialog`, profile dialogs, geometry/resize | shell (window chrome, not a tab) |

### 4.2 The handle a tab gets

```python
class PanelRuntime:
    profiles: profile.ProfileManager
    settings: SettingsBinder
    i18n:     Translator
    log:      LogBus
    game:     GameLink            # .evaluator(), .port, .up(), .jump(), .claim()/.release()
    actions:  ActionRunner        # .run(name, args, on_event) -> bool
    children: ChildFactory
    tick:     Ticker
    schedule: Schedule | None     # None unless a tab's NEEDS asked for it
    bus:      EventBus
    tabs:     TabRegistry         # .get(id) -> PanelTab | None
    root:     tk.Misc             # for after()/winfo — NOT for building into

    def t(self, key, **fmt) -> str: ...
    def tr(self, widget, key, option="text", **fmt): ...
    def say(self, tag, key, **fmt) -> None: ...
```

Two members deserve their own words.

**`game.evaluator()`** wraps `lua_client.get_evaluator(port=…)` with the profile's
port already applied and hands back the warm daemon client — the ~0.1 s path instead
of the ~5 s cold one. `_ensure_daemon` lives behind it, so a tab that needs the game
says `rt.game.evaluator()` and the runtime decides whether to start the daemon, in
*both* launch modes. A tab never reads `_daemon_port` to build its own client again
(nine sites do that today).

**`actions.run(...)`** is `script_engine.run_action` with the context already built:
`hwnd=0`, the log as `on_event`, the busy lock claimed and released around it, the
result logged. It exists so a tab has an obvious one-line way to do the *right* thing
— see §8.

### 4.3 How this comes up in standalone

`PanelRuntime.standalone(profile, lang, port, needs)` runs the same constructor the
shell uses, in this order:

1. `ProfileManager()` → active profile (`--profile` overrides, created if missing);
2. `SettingsBinder` reads that profile's `config.json`; `--daemon-port` overrides the
   stored port for this run only (never written back);
3. `Translator` with the profile's language (`--lang` overrides);
4. `debug_log` pointed at the profile's `debug.log`, exception hooks installed;
5. `LogBus` opened on the profile's `panel.log` — a standalone run's lines land in the
   same file the shell writes, tagged the same way, **with no view attached** (§4.4);
6. `Ticker` bound to the standalone root;
7. `GameLink` created **cold** — no daemon is started until something asks;
8. `ChildFactory` with `LW_DAEMON_PORT` and `LW_GAME_LEASE` in the child environment,
   so a capture started from a standalone tab drives the client the profile names and
   shares its hold on the game (§7);
9. `Schedule` **only if** the tab's `NEEDS` contains `"schedule"` — a standalone rally
   tab must not start the whole account's errands;
10. `EventBus`, and a `TabRegistry` holding exactly one tab.

Everything a tab can reach is therefore identical between the two modes. There is no
longer a "standalone is weaker here" clause: the game lock is the daemon's (§7), so
two windows cannot both drive the game whichever way they were started.

### 4.4 The log is the shell's, not the runtime's face

**Decided: a standalone tab has no log pane.** It shows its own content and nothing
else; the log widget, the producer filter, the DSL command line and the account
strip belong to the container's «Главная» tab, which is not a plugin and does not
move.

What the runtime keeps is the **sink**, not the view. `rt.say(...)` and
`rt.log.put(...)` work identically in both modes — a tab never needs to know which
one it is in — but where the line comes out differs:

| | shell | standalone |
|---|---|---|
| the `LogView` widget on «Главная» | ✅ | — |
| the profile's `panel.log` | ✅ | ✅ |
| the profile's `debug.log` | ✅ | ✅ |
| stdout of the launching console | — | ✅ |

So a standalone tab is still readable while it runs (the console it was started
from) and still leaves the same record behind (the profile's two files) — it just
does not carry a copy of the shell's chrome around with it.

`LogBus` therefore stays in `panel/runtime/log.py` and `LogView` moves to the shell.
The `--no-log` CLI flag is dropped: there was never anything to hide.

### 4.5 The standalone CLI

```
python -m panel.tabs.rally [options]

  --profile NAME     which profile's settings and logs to use (default: the active one)
  --lang en|ru       override the profile's language
  --geometry WxH     window size (default: the tab's PREFERRED_SIZE)
  --daemon-port N    override the profile's daemon port for this run
  --read-only        build the tab but refuse every press that drives the game
```

Every tab module ends with four lines:

```python
if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(RallyTab))
```

`run_tab` builds the runtime, creates a `tk.Tk` root titled `<tab> — <profile>`, puts
the tab alone in it (no log pane — §4.4), runs §3.3's sequence, wires
`WM_DELETE_WINDOW` → `tab.shutdown()` → `rt.shutdown()`, and enters `mainloop()`.
`python -m panel.tabs --list` prints the registry (id, title, order, default-enabled,
`NEEDS`) so the CLI is discoverable.

---

## 5. The registry and the profile

`panel/tabs/__init__.py` holds an explicit table — no import scanning, and lazy so a
standalone run imports one tab, not fourteen:

```python
TABS: tuple[TabSpec, ...] = (
    TabSpec("scenarios", "panel.tabs.scenarios", "ScenariosTab", order=20),
    TabSpec("timers",    "panel.tabs.timers",    "TimersTab",    order=30),
    TabSpec("settings",  "panel.tabs.settings",  "SettingsTab",  order=40),
    TabSpec("chat",      "panel.tabs.chat",      "ChatTab",      order=50),
    …
    TabSpec("develop",   "panel.tabs.develop",   "DevelopTab",   order=900,
            default_enabled=False),
)
```

Resolution:

```
enabled = profile["tabs"]["enabled"]  if present else  [t.id for t in TABS if t.default_enabled]
order   = profile["tabs"]["order"]    if present else  sorted by TabSpec.order
```

* An id in the profile that no longer exists in code → **skipped, one log line.** A
  profile written by a newer build must not break an older panel.
* A tab in code the profile has never heard of → **appended at its `order`**, enabled
  if `default_enabled`. A new tab appears without editing every profile by hand.
* A tab whose import or `build()` raises → **skipped, traceback to the debug log, the
  panel still opens.** This alone is worth the refactor.

**Settings storage.** Today `config.json` is one flat dict with three nested blocks
(`autorally`, `rally_tab`, `command_post`). Target:

```json
{
  "language": "ru",
  "window_geometry": "760x600+100+100",
  "tabs": {
    "enabled": ["scenarios", "timers", "settings", "rally", "secret_tasks"],
    "order":   ["scenarios", "timers", "rally", "secret_tasks", "settings"],
    "config": {
      "rally":        { "kind": "elite", "level": 5, "squads": [1, 2] },
      "secret_tasks": { "monitor": true, "interval": "2", "autoloot": false }
    }
  }
}
```

**Compatibility, in three rules:**

1. **Read old → new.** On load a tab's block is `tabs.config[<id>]` if present;
   otherwise the binder reads that tab's `LEGACY_KEYS` from the flat top level
   (`secret_tasks.monitor` ← `secret_monitor`, `.interval` ← `monitor_interval`, …).
   The existing per-key fallbacks stay (`autoloot_level_from` still falls back to
   `filter_level_from` — that migration is already in `_apply_settings_to_ui` and is
   not re-litigated here).
2. **Dual-write for one release.** Save writes the new block **and** the legacy flat
   keys, so a profile touched by the new panel still opens in the old one. Drop the
   dual write later, in its own commit.
3. **No key renames during the move.** A wave that moves a tab may not also rename its
   settings keys. Rename separately, before or after — otherwise a lost setting is
   indistinguishable from a migration bug.

A profile that has never seen the new panel keeps every value it had and gets the
default tab list. `panel/settings.json` (the global active-profile pointer) is not
touched at all.

---

## 6. Settings pages come from the tabs

`SETTINGS_TABS` is already a table of `(key, builder-method)`. Under the plugin model
the Settings tab becomes an **aggregator**: it renders the runtime's own pages
(«Общие», «Игра», «Отладка», «Вкладки») plus one page per tab that defines
`settings_page`. «Авторалли» is then contributed by the rally tab and travels with it;
switch rally off and its settings page is not there either.

The new «Вкладки» page is the UI over `tabs.enabled` / `tabs.order`: a checkbox and
up/down per tab, with the tab's `NEEDS` shown beside it. Toggling takes effect on
restart in wave 1; live add/remove (build on enable, `shutdown()` + destroy on disable)
is optional and belongs in wave 7, not earlier.

---

## 7. What the shell gets for free — and the one thing it cannot

Four hand-written lists become loops. This is the measurable payoff and belongs in
wave 7's acceptance criteria:

| Today | After |
|---|---|
| `_sync_monitors` — 55 lines naming every subsystem | `for tab in rt.tabs.live: tab.on_profile_switch()` |
| `_panic` — 30 lines | `for tab in rt.tabs.live: tab.panic()` |
| `_on_close` — 33 lines | `for tab in rt.tabs.live: tab.shutdown()` then `rt.shutdown()` |
| `_apply_language` + the 14-entry `tab-titles` hook | `Translator.retranslate()` + one loop |

### The game lock moves into the daemon — in scope, not deferred

`_claim_busy` / `_release_busy` is a *process-wide* mutex keeping two recipes out of
the game VM at once. The moment tabs can be launched separately that is not enough:
two windows are two processes, two locks, one game. **Decided: the lock becomes the
daemon's, as part of this refactor.** A warning in the log is not a lock.

The daemon already serialises individual `run` calls with a `threading.Lock` — but an
*action* is many chunks over seconds, and that is the thing that must not interleave.
So the daemon grows a **lease**, three ops beside the existing ones:

```
{"op":"acquire","owner":"panel/rally","ttl":120}  -> {"ok":true,"token":"…"}
                                                  |  {"ok":false,"busy":"panel/timers",
                                                  |   "held_sec":8.2}
{"op":"renew","token":"…"}                        -> {"ok":true}
{"op":"release","token":"…"}                      -> {"ok":true}
{"op":"run","chunk":…,"token":"…"}                -> renews the lease as a side effect
```

Five rules, each earning its place:

1. **A lease excludes other leases, never plain `run`s.** Today the read-only tabs and
   the account poll call `ev.run()` without claiming anything, and they interleave with
   a running action at chunk granularity. Blocking them behind a lease would freeze the
   dashboard for the length of every recipe and would be a behaviour change smuggled
   into a refactor. Per-call serialisation stays exactly as it is.
2. **A lease expires.** `ttl` seconds without a renew and the daemon drops it, so a
   client that crashed mid-action cannot wedge the game until someone restarts the
   daemon. Every `run` carrying the token renews it, so a working action never expires.
3. **Children inherit it.** The token travels to child processes in `LW_GAME_LEASE`
   beside `LW_DAEMON_PORT`; `lua_client` picks it up and attaches it to every `run`.
   Without this, auto-loot — which holds the lease and then spawns the tool that does
   the robbing — would deadlock against itself.
4. **Re-acquiring with a token you already hold is a no-op that returns it.** Same
   reason: nested claims inside one owner must not self-deadlock.
5. **No daemon, no lease — and no game either.** If the daemon is unreachable
   `GameLink.claim()` falls back to the in-process lock alone. Nothing can be driving
   the game in that state anyway, so the fallback is honest rather than a hole.

`GameLink.claim()` takes both: the in-process lock (two Tk threads in one panel) and
the daemon lease (two processes). `release()` drops both. The panel's existing
`_claim_busy` becomes a one-line delegation, so every current caller is covered
without being touched.

This lands in wave 0 as its own commit, with its own test — the daemon and the client
are plain sockets and JSON, so it is testable without Tk and without the game.

### Cross-tab talk

Five places reach across tabs today; each gets an explicit route:

| Today | After |
|---|---|
| `_nudge_secret_tasks_tab` (capture line → the list) | `rt.bus.publish("secret.finding", rec)` |
| `_refresh_inventory_tab` after a collect | `rt.bus.publish("inventory.changed")` |
| resource tracker → stats tab | `rt.bus.publish("resources.gained", gains)` |
| secret-tasks row → share into chat | direct `tools/lib/chat_share.py` call — no tab needed |
| log coord link → jump | `rt.game.jump(...)` — runtime, not a tab |

The bus is deliberately tiny: `publish(topic, payload)` delivered on the Tk thread,
`subscribe(topic, fn)` returning an unsubscribe callable that `shutdown()` calls. No
wildcards, no ordering guarantees, no persistence. Anything needing more than that is a
runtime service, not an event.

---

## 8. Moving *toward* the actions-first rule

`CLAUDE.md` is binding: an ability is one `src/lastwar_bot/actions/*.md` scenario and
the panel only plays it. This refactor must not cement the current violations. Three
consequences.

**It is not an ability.** No new `actions/*.md` is owed by the refactor itself, no
`docs/farming.md` entry, no progress-bar redraw. It changes who owns code, not what the
bot can do.

**Relocation is not payment.** Waves 2, 3 and 5 carry Lua sequences and gates from
`__main__.py` into a tab package. That is a move, and must not be reported as the debt
being paid.

**But the debt is now itemised, and three items are nearly free.** The scenarios already
exist and the panel bypasses them:

| Tab | What it does today | What it should do | Scenario |
|---|---|---|---|
| Rally | `RallyTab._one_send` calls `rally_create.create_on_level(ev, …)` directly | **not a one-line swap** — see the note below | `create_rally.md` exists |
| Secret tasks | `_autoloot_run` spawns `tools/steal_secret_task.py` as a child | `rt.actions.run("steal_secret_task", …)` | `steal_secret_task.md` **exists** |
| Command post | `_ghost_run` spawns `tools/ghost_recon_steal.py` as a child | `rt.actions.run("steal_ghost_recon", …)` | `steal_ghost_recon.md` **exists** |
| Secret tasks | the auto-loot gate (range, budget, "is it raidable") is ≈290 lines of Python in `_autoloot_*` | the gate belongs in the scenario; the tab keeps the switch and the range | needs `ARGS` on the existing file |
| Command post | ghost `IsOpenDay` / 5-per-day gate in `_ghost_tick` | same | same |
| Dashboard, Alliance/Profile/Inventory/Heroes | read the VM through hand-written Lua chunks in Python | `READ_LUA` scenarios | not written |

> **Correction, found in wave 2.** The rally row above was over-claimed. The other two
> only *spawn the tool the scenario already wraps*, so swapping them for
> `rt.actions.run(...)` costs nothing. Rally does not: `create_on_level` returns a
> result the tab reads four ways (`no_elite` / `no_formation` / `no_panel` /
> `no_squad`), each reported differently to the operator, and `run_action` answers with
> a bool. Swapping it as-is would trade four diagnoses for "it did not work", which is a
> behaviour regression wearing a refactor's clothes. Doing it properly means the
> scenario reporting its own reason back — a task of its own, filed separately, not
> smuggled into a wave that is moving code.

Rule for the migration: **a wave may move debt; it may not create it.** No new direct
game logic may be added under `panel/`. Where a wave lifts a block that merely *spawns
the tool the scenario already wraps* (the top three rows), swap it to
`rt.actions.run(...)` in the same wave — a one-line change, and the whole reason
`ActionRunner` is in the runtime. Where the gate itself has to move into the scenario
(rows four and five), that is its own task, filed separately, not smuggled into a
refactor wave.

---

## 9. What is in the way — the coupling inventory

Named, because "it's coupled" is not a plan. Pain is rated **low** (mechanical),
**medium** (needs thought per case), **high** (can silently break behaviour).

### 9.1 Tk variables the tab builds and the app owns — **medium**

Eighteen assignments of the form `app._x = tk.Var(...)` inside tab modules:

| File | What it plants on the app |
|---|---|
| `secret_tasks.py` | `_mon_combo`, `_mon_var`, `_interval_var`, `_star_var`, `_pending_var`, `_can_loot_var`, `_flt_from_var`, `_flt_to_var`, `_sweep_var`, `_sweep_cx_var`, `_sweep_cy_var`, `_sweep_hint`, `_autoloot_var`, `_lvl_from_var`, `_lvl_to_var`, `_autoloot_chk`, `_autoloot_rule_lbl` |
| `command_post.py` | `_ghost_autoloot_var` |

They are app-owned because `_collect_settings` / `_apply_settings_to_ui` /
`_install_autosave` name them, and because the handlers reading them
(`_toggle_monitor`, `_toggle_sweep`, `_toggle_autoloot`, `_toggle_ghost_autoloot`) also
live on the app. The construction order is already load-bearing and commented as such:
the tabs are built *before* settings are applied so the vars exist.

*Why medium, not low:* moving a var and its handler together is mechanical, but each of
these switches gates a **budget** — the auto-loot range aims real robberies, and a
mis-wired range robbed the wrong level once already (#1099). The move is safe only if
the var, its handler, the rule-hint label and the debounced restart move as one piece,
in one wave, with nothing else in the diff.

### 9.2 The three parallel settings lists — **medium**

`_collect_settings` writes ≈29 keys, `_apply_settings_to_ui` sets ≈22, and
`_install_autosave` traces ≈18 — three hand-maintained lists in three methods that must
agree, plus the `config()`/`apply_config()`/`persist_vars()` triple `RallyTab` and
`CommandPostTab` already added on the side, plus the `_loading` flag that suppresses
saves while applying.

`SettingsBinder.bind_tab(tab)` collapses the three into one registration driven by
`SETTINGS` + `persist_vars()`. *Why medium:* a key silently dropped from one of the
three lists is a setting that stops persisting, and nothing fails loudly. The
compatibility test of §11 is the guard, and it must be written **before** the first tab
moves, not after.

### 9.3 Handlers in `__main__.py` that tab widgets point at — **medium/high**

`command=app._toggle_monitor`, `app._toggle_sweep`, `app._toggle_autoloot`,
`app._toggle_ghost_autoloot`, and behind each of them a machine: the capture child
(`_start/_stop_monitor`, `_task_passes`, `_on_secret_line`, ≈150 lines), the auto-loot
watcher (`_autoloot_*`, ≈290), the map sweep (`_sweep_*`, ≈210), the ghost order
(`_ghost_*`, ≈100). Also `app._jump`, `app._read_resource_balance`, `app._child`,
`app._say`, `app._arm`, `app._claim_busy`.

The last six are **low** — they become runtime calls and the rename is mechanical. The
four machines are **high**: they own subprocesses, threading events, daily budgets and
profile-switch restarts, and they are the part of the panel most likely to be running
unattended overnight. They are why wave 3 stands alone and carries no behaviour change.

### 9.4 Language hooks — **low**

Nine `_hook(...)` registrations (`_build_menu`, the 14-entry `tab-titles` lambda,
`_update_path_hints`, `_retranslate_log_menu`, the settings sub-tabs,
`_paint_chat_tabs`, `_retranslate_chat_bottom`, plus `app._retranslate_capture_combo`
from `secret_tasks.py` and `app._hook(self._retranslate)` from `command_post.py`),
against ≈100 `_tr(...)` call sites in `__main__.py` alone.

Mechanical: the weak registry and the `key=` de-duplication from #1177 move into
`Translator` unchanged, the `tab-titles` lambda is deleted outright (the shell
retranslates titles from `TITLE_KEY` in a loop), and a tab needing more registers its
own `on_language_change`. Nothing here breaks silently — a missed hook is a label that
visibly stays in the other language.

### 9.5 Sentinel scenarios in the trigger catalogue — **low**

`__inventory_refresh__`, `__leaderboard_collect__`, `__secret_task_share__` are
dispatched by `if` in the runner. §3.2 replaces them with `TriggerSpec(handler=…)` on
the owning tab. Mechanical, and it removes a class of bug: a trigger switched on for a
tab that is not there.

### 9.6 Construction-order landmines — **medium**

Documented in the code and easy to re-break: tabs are built before
`_apply_settings_to_ui` because that method reads vars the tabs create;
`CommandPostTab` is built eagerly rather than lazily for the same reason; the splash
holds the boot open while `_startup_boot` runs on a thread and posts `after(0, …)`
callbacks. The registry's fixed sequence (§3.3) makes the order explicit instead of
incidental — build all, bind all, apply all, then load lazily.

### 9.7 Not in the way, worth saying

`panel/profile.py`, `panel/widgets.py`, `panel/childmon.py`, `panel/debug_log.py`,
`panel/splash.py`, `panel/chat_history.py`, `panel/rally_limits.py`,
`panel/resource_stats.py`, `panel/mapsweep.py` are already UI-agnostic or
single-purpose and are used as-is by the runtime. The refactor does not touch them.

---

## 10. Migration order and size

Seven waves. Each is a separate commit (or a small stack), each leaves the panel fully
working, each has an acceptance check to run before the next starts. Ordering is by
coupling, cheapest first — the early waves buy the contract its evidence before the
expensive tabs bet on it. Sizes are **lines relocated**, not written; the diffs are
mostly moves.

| # | Wave | Moves | Size | Risk |
|---|---|---|---|---|
| 0 | Runtime package + the daemon lease | §4.1 table; `lua_daemon.py`/`lua_client.py` | ≈1 500 out of `__main__.py`, +10 files, +150 in the daemon | low, widest diff |
| 1 | `PanelTab` + registry + `run_tab` + 6 read-only tabs | `tabs_extra.py` (minus rally) + stats + dashboard strip | ≈700 | low |
| 2 | Rally | form + monitor + caps + «Авторалли» page | ≈460 | medium |
| 3 | Secret tasks + Command post | capture, auto-loot, sweep, ghost | ≈650 | **high** |
| 4 | Scenarios | list, editor, runner, loop | ≈480 | low |
| 5 | Schedule split, then Timers/Triggers tab | runtime half ≈250, tab ≈800 | ≈1 050 | medium |
| 6 | Chat, Settings aggregator, Develop tab | ≈1 050 + 400 + 450 | ≈1 900 | medium |
| 7 | Cleanup: delete shims, four loops, «Вкладки» page | — | ≈300 removed | low |

**Wave 0 — the runtime, no UI change.** Create `panel/runtime/` and move §4.1 into it.
`Panel` keeps every current method name as a one-line delegation, so untouched code in
`__main__.py` keeps working while tabs move out one at a time. No tab moves; no file
under `panel/tabs/` exists yet.
*Accept:* the panel opens; every existing `tests/test_panel_*.py` passes unchanged; the
diff of `__main__.py` is deletions and shims only. Do it alone, review it alone.

**Wave 1 — the contract and its first six.** `panel/tabs/base.py` + `__init__.py` + the
profile's `tabs` block with its compatibility rules. Migrate the tabs that only read:
Alliance, Profile, Inventory, Heroes, Accounts (dashboard strip included) and Stats.
*Accept:* `python -m panel.tabs.heroes --profile default` opens and loads;
`python -m panel.tabs --list` prints six ids; the shell is visually identical; an old
`config.json` opens with every value intact.

**Wave 2 — Rally.** `panel/tabs/rally/`: the create form, the monitor
(`_build_rally_monitor`, `_start/_stop_rally`, `_on_rally_line`, the alert,
`_join_rally_now`), the daily caps (`rally_limits.py` + `_rally_join_gate`,
`_record_rally_joins`), the «Авторалли» settings page — the first user of
`settings_page` — and the one-line swap to `rt.actions.run("create_rally", …)` (§8).
*Accept:* standalone rally raises a rally and joins one; the caps still gate; the
settings page appears in the shell and disappears when rally is off.

**Wave 3 — Secret tasks + Command post.** The §9.1/§9.3 machinery, moved whole: capture
child, auto-loot watcher, map sweep, ghost order, and the Tk vars that gate them.
*Accept:* a profile switch still bounces both captures and both watchers (now via
`on_profile_switch`); «Стоп всё» still stops them (via `panic`); the standalone tab robs
a tile; the auto-loot range still restarts the push listener on edit (#1099's fix).
**Do not fold a behaviour change into this wave.**

**Wave 4 — Scenarios.** List, editor with its debounced save, runner, repeat loop. The
only runtime it needs is `actions`, the busy lock and the log.
*Accept:* standalone scenarios edits, saves and runs an `actions/*.md`; the loop stops
on «Стоп всё».

**Wave 5 — Schedule, then Timers.** First `runtime/schedule.py` (scheduler, watcher,
catalogue load/save, the runner, the gate) — the rally gate and the triggers already
depend on it. Then `panel/tabs/timers/`: the grid, the editor dialog, the trigger rows,
grouped by contributing tab (§3.2).
*Accept:* **the schedule keeps firing with the Timers tab disabled in the profile** —
that is the test that the split is real and not cosmetic.

**Wave 6 — Chat, Settings, Develop.** `panel/tabs/chat/` (views, DM pane, emoji picker,
image cache, reader child, per-character store); Settings becomes the aggregator of §6;
the Develop-menu sniffers become `panel/tabs/develop.py` with `default_enabled=False`.
*Accept:* standalone chat reads and sends; a profile with chat disabled starts no reader
child and opens no store.

**Wave 7 — Cleanup.** Delete the delegating shims. Replace `_sync_monitors`, `_panic`,
`_on_close` and the tab-title hook with §7's four loops. Add the «Вкладки» page.
`panel/__main__.py` should land under ~900 lines — the shell plus «Главная».
*Accept:* `grep -n "self\._t(" panel/__main__.py` returns shell chrome only; the four
loops exist; `tests/test_panel_leaks.py` is green.

---

## 11. Testing

The fakes already exist; they get promoted.

* **`tests/fake_runtime.py`** — one `FakeRuntime` replacing the hand-rolled `_App`
  stand-ins in `test_panel_tabs_extra.py`, `test_panel_rally_tab.py`,
  `test_panel_secret_tasks.py`, `test_panel_command_post.py`: echoing `t()`, a recording
  `LogBus`, a `GameLink` that refuses to connect, a `ChildFactory` that records commands
  instead of spawning, an `ActionRunner` that records `run()` calls.
* **A contract test, parametrised over `TABS`.** Each tab imports, builds on a bare Tk
  root against a cold runtime, requests no evaluator during `build()` (§3.1), survives
  `apply_config({})` → `on_show` → `on_hide` → `panic` → `shutdown`, and leaves no armed
  `after` chain. A new tab is covered the day it is registered. Skips without a display,
  like the existing ones.
* **A profile-compatibility test** — a frozen pre-migration `config.json` fixture loads
  and yields the same effective values per tab. **Written in wave 0, before any tab
  moves** (§9.2).
* **A locale-ownership test** — §12.
* **A daemon-lease test** — two clients against one daemon: the second `acquire` is
  refused while the first holds it, a lease expires without renewal, a `run` carrying
  the token renews it, and a plain `run` is never blocked by someone else's lease (§7).
  Plain sockets and JSON, so it needs neither Tk nor the game.
* `tests/*.py` here are self-running scripts under Windows Python (no pytest in this
  environment); the new ones follow that shape.

---

## 12. Decisions taken, so they can be argued with

The first three were put to the operator as open questions and answered; they are
settled and the rest of this document is written to them.

* **The locale files are not split.** `panel/locales/en.json` is 601 keys, flat,
  mirrored by `ru.json`. Splitting per tab is rejected: the EN/RU mirroring discipline
  is easier to hold over two files than twenty-eight, a standalone tab loading 36 KB of
  JSON costs nothing measurable, and key renames are what §5 rule 3 forbids
  mid-migration. Instead each tab **declares** its prefixes (`LOCALE_NS`), and a test
  walks each tab module for `t("…")` literals and fails when it reads a key outside its
  own namespaces plus a shared `common.*` list. Splitting stays mechanically available
  later, once every namespace has exactly one owner.
* **The game lock becomes the daemon's, inside this refactor** (§7). Two standalone
  windows must not be able to drive the game at once, and a warning in the log is not a
  lock. Lands in wave 0 with its own test.
* **The log belongs to the shell, not to a standalone tab** (§4.4). «Главная» stays a
  container tab holding the log, the producer filter, the DSL line and the account
  strip; it is not a plugin and does not move. A standalone tab shows its own content
  only — the runtime still carries the *sink*, so `rt.say(...)` works identically and
  the lines land in the profile's `panel.log`, `debug.log` and the launching console.
* **No third-party tab loading.** A `panel/tabs_local/` scan for user-written tabs is an
  evening's work on top of the registry, but it would mean promising `PanelRuntime`
  stability that the migration itself still needs to break.
* **No settings key renames**, and **no behaviour change inside a migration wave.** A
  wave that both moves a tab and changes what it does cannot be reviewed, and cannot be
  bisected when a budget goes wrong a week later.
