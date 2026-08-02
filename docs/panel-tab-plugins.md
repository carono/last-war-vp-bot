# Panel tabs as self-contained runnable modules

A migration plan. The goal: every tab of the control panel is a module that can be
run on its own —

```
C:\Python312\python.exe -m panel.tabs.rally --profile main
```

— and opens a working window with just that tab in it. The panel itself becomes a
**shell**: it holds the window, the notebook and the log, and plugs tabs in as
listed in the active profile.

Read against `panel/__main__.py`, `panel/tabs_extra.py`, `panel/secret_tasks.py`,
`panel/command_post.py`, `panel/profile.py`, `panel/i18n.py`. Nothing here changes
what the panel *does*; it changes who owns what.

---

## 1. Why

`panel/__main__.py` is ≈7 600 lines and `Panel(tk.Tk)` is two things at once: the
application window *and* the runtime every tab leans on. The measured shape today:

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

The tabs that *were* extracted (`tabs_extra.py`, `secret_tasks.py`,
`command_post.py`) are classes taking `(app, parent)` and reaching back into the
app by private attribute. Counted across those three files: `app._tr` 82 times,
`app._t` 48, plus `app._daemon_port`, `app._profiles`, `app._log_put`, `app._arm`,
`app._child`, `app._say`, `app._python`, `app._jump`, `app._claim_busy`,
`app._read_resource_balance` — and a dozen **Tk variables the tab builds but the app
owns** (`_mon_var`, `_sweep_var`, `_ghost_autoloot_var`, `_lvl_from_var`, …).

That coupling costs four concrete things:

1. **A tab cannot be run, tested or demoed on its own.** Trying one change to the
   rally form means booting the whole panel: the daemon, the monitors, the chat
   store, the schedule.
2. **A tab that raises during build kills the boot.** `_build_ui` is one straight
   line of fourteen constructions.
3. **Every lifecycle event is a hand-written list.** `_sync_monitors`, `_panic`,
   `_on_close` and `_apply_language` each enumerate the subsystems by name, and a
   new tab means remembering all four.
4. **Nothing can be switched off.** An operator who never uses chat still pays for
   its subprocess, its SQLite store and its image cache.

The tests already show what the answer looks like: `tests/test_panel_tabs_extra.py`
and `tests/test_panel_rally_tab.py` each hand-roll a minimal `_App` stand-in with
`_t`, `_tr`, `_daemon_port`, `_daemon_up`, `_read_resource_balance`. That ad-hoc
fake **is** the interface — this plan writes it down and makes it real.

---

## 2. Target shape

```
panel/
  __main__.py          the shell: window, notebook, menu, log pane, status strip
  runtime/
    __init__.py        PanelRuntime — assembled by the shell OR by a standalone tab
    i18n.py            Translator: t(), tr() weak registry, hook(), set_lang()
    log.py             LogBus (thread-safe sink, tags, severity, panel.log mirror)
                       + LogView (the widget; the bus does not need it)
    settings.py        SettingsBinder: profile-scoped values, autosave, per-tab blocks
    daemon.py          GameLink: client, port, ensure/restart, one-action-at-a-time lock
    children.py        child process factory (panel/childmon.py stays the monitor)
    tick.py            arm/disarm named repeating callbacks, on_tk()
    schedule.py        TimerScheduler + TriggerWatcher wiring (runtime half of Timers)
    bus.py             tiny publish/subscribe for cross-tab facts
    captures.py        CAPTURE_OPTIONS and friends (no longer stashed on the app)
  tabs/
    __init__.py        the registry: id -> module:class, order, default-enabled
    base.py            PanelTab (the interface) + run_tab() (the standalone harness)
    __main__.py        `python -m panel.tabs --list`
    alliance.py  profile.py  inventory.py  heroes.py  accounts.py  stats.py
    rally/  secret_tasks/  command_post/  scenarios.py  timers/  chat/  develop.py
  profile.py  widgets.py  splash.py  debug_log.py  childmon.py  … (unchanged)
```

Two rules make the split hold:

* **A tab imports from `panel.runtime` and `panel.widgets`, never from
  `panel.__main__`.** This is not style — `python -m panel` executes `__main__.py`
  *as* `__main__`, so `from . import __main__` inside a tab re-executes the whole
  file as a second module. That is why `CAPTURE_OPTIONS` is stashed on the
  instance today (`self.capture_options`); once it lives in
  `panel/runtime/captures.py` the workaround goes.
* **A tab may be absent.** Anything that reaches another tab goes through
  `rt.tabs.get("<id>")` and tolerates `None`, or through the bus. The panel already
  does this by accident (`getattr(self, "_secret_tasks_tab", None)`); the plan makes
  it the contract.

---

## 3. What moves into the runtime

One table, because "the shared runtime" is only as good as its list.

| Today (`Panel` member) | New home | Note |
|---|---|---|
| `_i18n`, `_t`, `_tr`, `_hook`, `_tr_widgets`, `_sweep_tr_widgets`, `_apply_language`, `_set_language` | `runtime/i18n.py::Translator` | weak-registry logic moves verbatim |
| `_log_q`, `_log_put`, `_say`, `_pump_log`, `_append_log`, `_open/_close_panel_log`, `_log_tag`, `_log_severity`, `_log_cap`, `_trim_log` | `runtime/log.py::LogBus` | no Tk in the bus |
| `_log`, `_insert_line`, `_redraw_log`, `_clear_log`, `_install_log_copy`, coord/photo links | `runtime/log.py::LogView` | the shell owns one; `run_tab` gets a small one |
| `_profiles`, `_settings`, `_opt_vars`, `_opt*`, `_collect_settings`, `_apply_settings_to_ui`, `_install_autosave`, `_loading`, `_save_settings` | `runtime/settings.py::SettingsBinder` | `panel/profile.py` unchanged underneath |
| `_client`, `_daemon_port`, `_daemon_up`, `_ensure_daemon`, `_restart_daemon`, `_rebind_daemon`, `_current_server`, `_act`, `_claim_busy`, `_release_busy` | `runtime/daemon.py::GameLink` | the busy lock is **process-wide**, see §9 |
| `_child`, `_child_env`, `_python` | `runtime/children.py` | wraps `panel/childmon.py` |
| `_arm`, `_disarm`, `_disarm_all`, `_on_tk`, `_loops` | `runtime/tick.py` | named chains; keeps #1177's one-chain-per-name rule |
| `_timers`, `_triggers`, catalogue load/save, `_run_timer_action`, `_timer_gate`, `_errand_args`, `submit` | `runtime/schedule.py` | the Timers **tab** is only its grid and editor |
| `_configure_debug_log`, `_dbg*`, `_install_exception_logging` | `runtime/__init__.py` + existing `panel/debug_log.py` | re-pointed per profile |
| `_jump`, `_on_coord_click` | `runtime/daemon.py` | the log's coord links call it; no tab owns it |
| `_refresh_status`, `_poll_status`, `_watchdog_check`, `_launch_game`, `_restart_game` | shell, exposed as `rt.game_status()` | it is the status strip's subject |
| `_build_menu`, `_show_about`, `_open_send_log_dialog`, profile dialogs, geometry/resize | shell | window chrome, not a tab |

`PanelRuntime` is the handle a tab gets:

```python
class PanelRuntime:
    profiles: profile.ProfileManager
    settings: SettingsBinder
    i18n:     Translator
    log:      LogBus
    game:     GameLink
    children: ChildFactory
    tick:     Ticker
    schedule: Schedule | None      # None in a standalone tab that did not ask for it
    bus:      EventBus
    tabs:     TabRegistry          # .get(id) -> PanelTab | None
    root:     tk.Misc              # for after()/winfo; NOT for building into

    # shorthands every tab uses constantly
    def t(self, key, **fmt) -> str: ...
    def tr(self, widget, key, option="text", **fmt): ...
    def say(self, tag, key, **fmt) -> None: ...
```

The shell keeps `_t`/`_tr`/`_log_put`/`_daemon_port`/… as one-line delegations to
the runtime **for the whole migration**, so untouched code in `__main__.py` keeps
working while tabs move out one at a time. The shims are deleted in wave 7.

---

## 4. The tab interface

```python
class PanelTab:
    """One tab. Built into a frame; knows nothing about the notebook around it."""

    ID: str                          # "rally" — the key in the profile and the CLI
    TITLE_KEY: str                   # "tab.rally"
    ORDER: int = 100                 # default position in the notebook
    DEFAULT_ENABLED: bool = True     # is it in a fresh profile's list
    LOCALE_NS: tuple[str, ...] = ()  # locale prefixes this tab owns ("rally_tab", "rally")
    NEEDS: frozenset = frozenset()   # "daemon" | "children" | "schedule" | "chat_store"
    SETTINGS: dict = {}              # key -> default, stored in the profile's tab block
    LEGACY_KEYS: dict = {}           # new key -> old flat key in config.json (see §6)

    def __init__(self, rt: PanelRuntime, parent: ttk.Frame) -> None: ...

    # -- construction ------------------------------------------------------
    def build(self) -> None: ...            # widgets only; must not touch the game
    def settings_page(self, parent) -> None | Callable
                                            # optional page contributed to Settings
    SETTINGS_PAGE_KEY: str = ""             # its title key ("settings.tab.autorally")

    # -- lifecycle ---------------------------------------------------------
    def ensure_loaded(self) -> None: ...    # first time it is shown (lazy data read)
    def on_show(self) -> None: ...          # notebook selected it
    def on_hide(self) -> None: ...          # notebook left it
    def on_profile_switch(self) -> None: ...# re-point per-profile state, bounce children
    def on_language_change(self) -> None: ...# only if `tr()` is not enough
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

`build()` **must not** touch the game: a standalone tab has to open with no daemon,
no client and no network. Everything live goes in `ensure_loaded()`. This is
already the de-facto rule in `tabs_extra.py`; it becomes enforceable because the
standalone harness runs `build()` with a runtime whose `GameLink` is cold.

---

## 5. The entry point

`panel/tabs/base.py` carries the harness. Every tab module ends with four lines:

```python
if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(RallyTab))
```

```
python -m panel.tabs.rally [options]

  --profile NAME     which profile's settings and logs to use (default: the active one)
  --lang en|ru       override the profile's language
  --no-log           hide the log pane under the tab
  --geometry WxH     window size (default: the tab's own PREFERRED_SIZE or 760x600)
  --daemon-port N    override the profile's daemon port
  --read-only        build the tab but refuse every press that drives the game
```

`run_tab` does, in order:

1. parse args, build `PanelRuntime.standalone(profile, lang, port)` — the same
   constructor the shell uses, minus the notebook, the menu and the schedule
   (unless the tab's `NEEDS` asks for it);
2. create a `tk.Tk` root, title it `<tab title> — <profile>`;
3. a `LogView` in the lower pane (unless `--no-log`) bound to the same `LogBus`;
4. `tab = cls(rt, frame)`, `tab.build()`, `rt.settings.bind_tab(tab)`,
   `tab.apply_config(...)`, `tab.ensure_loaded()`;
5. `WM_DELETE_WINDOW` → `tab.shutdown()` → `rt.shutdown()`;
6. `mainloop()`.

It is the *same* path the shell takes per tab; that is what keeps standalone
honest instead of a second implementation that rots. `python -m panel.tabs --list`
prints the registry (id, title, order, enabled-by-default, `NEEDS`) so the CLI is
discoverable.

---

## 6. The registry and the profile

`panel/tabs/__init__.py` holds an explicit table — no import scanning, and lazy so
a standalone run imports one tab, not fourteen:

```python
TABS: tuple[TabSpec, ...] = (
    TabSpec("scenarios",    "panel.tabs.scenarios",    "ScenariosTab",   order=20),
    TabSpec("timers",       "panel.tabs.timers",       "TimersTab",      order=30),
    TabSpec("settings",     "panel.tabs.settings",     "SettingsTab",    order=40),
    TabSpec("chat",         "panel.tabs.chat",         "ChatTab",        order=50),
    …
    TabSpec("develop",      "panel.tabs.develop",      "DevelopTab",     order=900,
            default_enabled=False),
)
```

The shell resolves the list to build like this:

```
enabled = profile["tabs"]["enabled"]  if present else  [t.id for t in TABS if t.default_enabled]
order   = profile["tabs"]["order"]    if present else  sorted by TabSpec.order
```

* An id in the profile that no longer exists in code → **skipped, one log line.**
  A profile written by a newer build must not break an older panel.
* A tab in code that the profile's list has never heard of → **appended at its
  `order`, enabled if `default_enabled`.** A new tab appears without editing every
  profile by hand.
* A tab whose import or `build()` raises → **skipped, the traceback goes to the
  debug log, the panel still opens.** This alone is worth the refactor.

**Settings storage.** Today `config.json` is one flat dict with three nested blocks
(`autorally`, `rally_tab`, `command_post`). Target:

```json
{
  "language": "ru",
  "window_geometry": "...",
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

1. **Read old → new.** On load, a tab's block is `tabs.config[<id>]` if present;
   otherwise the binder reads the tab's `LEGACY_KEYS` from the flat top level
   (`secret_tasks.monitor` ← `secret_monitor`, `.interval` ← `monitor_interval`, …).
   The existing per-key fallbacks stay (`autoloot_level_from` still falls back to
   `filter_level_from` — that migration is already in `_apply_settings_to_ui` and is
   not re-litigated here).
2. **Dual-write for one release.** Save writes the new block **and** the legacy
   flat keys, so a profile touched by the new panel still opens in the old one.
   Drop the dual write only after the user has run the new panel for a while — and
   say so in the commit that drops it.
3. **No key renames during the move.** A wave that moves a tab may not also rename
   its settings keys. If a name is wrong, rename it in a separate commit, before or
   after, never inside the migration — otherwise a lost setting is indistinguishable
   from a migration bug.

A profile that has never seen the new panel therefore keeps every value it had, and
gets the default tab list.

---

## 7. Settings pages come from the tabs

`SETTINGS_TABS` is already a table of `(key, builder-method)`. Under the plugin
model the Settings tab is an **aggregator**: it renders the runtime's own pages
(«Общие», «Игра», «Отладка», «Вкладки») plus one page per tab that defines
`settings_page`. «Авторалли» is then contributed by the rally tab and travels with
it; if rally is switched off, its settings page is not there either.

The new «Вкладки» page is the UI over `tabs.enabled` / `tabs.order`: a checkbox and
up/down per tab, with the tab's `NEEDS` shown beside it. Toggling takes effect on
restart in wave 1; live add/remove (build on enable, `shutdown()` + destroy on
disable) is optional and belongs in wave 7, not earlier.

---

## 8. i18n, and why the locale files are *not* split

`panel/locales/en.json` is 601 keys, flat, mirrored by `ru.json`. Splitting it per
tab (`locales/en/rally.json`) is the obvious move and is **rejected for now**:

* the mirroring discipline (EN and RU edited together) is easier to hold over two
  files than over twenty-eight;
* a standalone tab loading a 36 KB JSON costs nothing measurable;
* key renames are exactly what §6 rule 3 forbids during the migration.

Instead each tab **declares** the prefixes it owns (`LOCALE_NS`). That makes
ownership checkable without moving a byte: a test walks each tab module's source
for `t("…")` / `tr(…, "…")` literals and fails when a tab reads a key outside its
own namespaces plus a shared `common.*` list. Splitting the files stays available
later, mechanically, once every namespace has exactly one owner.

`Translator` keeps the weak-reference registry and the `hook(key=…)` de-duplication
from #1177 as they are; on a language change the shell calls
`Translator.retranslate()` then loops `for tab in rt.tabs: tab.on_language_change()`
— replacing the hand-written `nb.tab(...)` list of fourteen entries in `_build_ui`.

---

## 9. What the shell gets for free

Four lists that are hand-written today become loops. This is the measurable payoff
and belongs in the acceptance criteria of wave 7:

| Today | After |
|---|---|
| `_sync_monitors` — 55 lines naming every subsystem | `for tab in rt.tabs.live: tab.on_profile_switch()` + the runtime's own re-point |
| `_panic` — 30 lines | `for tab in rt.tabs.live: tab.panic()` |
| `_on_close` — 33 lines | `for tab in rt.tabs.live: tab.shutdown()` then `rt.shutdown()` |
| `_apply_language` + the 14-entry `tab-titles` hook | `Translator.retranslate()` + one loop |

**One thing the runtime cannot give away: the game lock.** `_claim_busy` /
`_release_busy` is a *process-wide* mutex that keeps two recipes out of the game VM
at once. Two standalone tabs running side by side are two processes and two locks
against one daemon — they *can* drive the game at the same time. `run_tab` must say
so on start (`log.warn("standalone: the one-action-at-a-time lock is per process")`),
and the plan does not pretend otherwise. Making the lock daemon-side is a separate
task, not a prerequisite for this one.

---

## 10. Cross-tab talk

Five places reach across tabs today; each gets an explicit route:

| Today | After |
|---|---|
| `_nudge_secret_tasks_tab` (capture line → the list) | `rt.bus.publish("secret.finding", rec)`; the tab subscribes |
| `_refresh_inventory_tab` after a collect | `rt.bus.publish("inventory.changed")` |
| resource tracker → stats tab | `rt.bus.publish("resources.gained", gains)` |
| secret-tasks row → share into chat | direct `tools/lib/chat_share.py` call — no tab needed |
| log coord link → jump | `rt.game.jump(...)` — runtime, not a tab |

The bus is deliberately tiny: `publish(topic, payload)` delivering on the Tk thread,
`subscribe(topic, fn)` returning an unsubscribe callable that `shutdown()` calls.
No wildcards, no ordering guarantees, no persistence. If a topic needs more than
that, it is a runtime service, not an event.

---

## 11. Migration order

Seven waves. Each is a separate commit (or a small stack), each leaves the panel
fully working, and each has an acceptance check that can be run before the next
starts. The ordering is by coupling, cheapest first — the early waves buy the
interface its evidence before the expensive tabs bet on it.

**Wave 0 — the runtime, no UI change.**
Create `panel/runtime/` and move §3's table into it. `Panel` keeps every current
method name as a one-line delegation. No tab moves, no file under `panel/tabs/`
exists yet.
*Accept:* the panel opens, every existing `tests/test_panel_*.py` passes unchanged,
`git diff --stat panel/__main__.py` shows only deletions and shims.
*Risk:* low, but it is the widest diff of the seven — do it alone, review it alone.

**Wave 1 — `PanelTab`, the registry, `run_tab`, and the six easy tabs.**
`panel/tabs/base.py` + `__init__.py` + the profile's `tabs` block with its
compatibility rules. Migrate the tabs that already only read: **Alliance, Profile,
Inventory, Heroes, Accounts** (from `tabs_extra.py`, dashboard strip included) and
**Stats**. `tabs_extra.py` is left holding only `RallyTab` until wave 2.
*Accept:* `python -m panel.tabs.heroes --profile default` opens and loads;
`python -m panel.tabs --list` prints six ids; the full panel is visually identical;
an old `config.json` opens with every value intact.

**Wave 2 — Rally.**
`panel/tabs/rally/`: the create form (from `tabs_extra.RallyTab`), the monitor
(`_build_rally_monitor`, `_start/_stop_rally`, `_on_rally_line`, the alert,
`_join_rally_now`), the daily caps (`panel/rally_limits.py` + `_rally_join_gate`,
`_record_rally_joins`) and the «Авторалли» settings page — the first tab to use
`settings_page`.
*Accept:* standalone rally raises a rally and joins one; the caps still gate; the
settings page appears in the shell's Settings tab and nowhere else when rally is off.

**Wave 3 — Secret tasks and Command post.**
The heaviest of the already-extracted pair. Into `panel/tabs/secret_tasks/`: the
capture child (`_start/_stop_monitor`, `_task_passes`, `_on_secret_line`), the
auto-loot watcher (`_autoloot_*`, ≈290 lines) and the map sweep (`_sweep_*`, ≈210).
Into `panel/tabs/command_post/`: the ghost order (`_ghost_*`). The Tk variables
those blocks build stop being the app's and become the tab's — this is the wave that
proves `config()`/`apply_config()`/`persist_vars()` carry real state.
*Accept:* a profile switch still bounces both captures and both watchers (now via
`on_profile_switch`), «Стоп всё» still stops them (now via `panic`), and the
standalone tab robs a tile.
*Risk:* highest of the seven — these hold budgets, and a mis-wired range robs the
wrong level (#1099). Do not fold a behaviour change into this wave.

**Wave 4 — Scenarios.**
`panel/tabs/scenarios.py`: the list, the editor with its debounced save, the runner
and the repeat loop. Self-contained subject; the only runtime it needs is the busy
lock and the log.
*Accept:* standalone scenarios edits, saves and runs an `actions/*.md`; the loop
still stops on «Стоп всё».

**Wave 5 — Schedule split, then Timers/Triggers.**
First `runtime/schedule.py` (scheduler, watcher, catalogue load/save,
`_run_timer_action`, the gate) — because the rally gate and the triggers already
depend on it. Then `panel/tabs/timers/`: the grid, the editor dialog, the trigger
rows.
*Accept:* the schedule keeps firing with the Timers tab **disabled** in the profile
— that is the test that the split is real and not cosmetic.

**Wave 6 — Chat, and Settings as an aggregator.**
`panel/tabs/chat/`: views, DM pane, emoji picker, the image cache, the reader child,
the per-character store. Then Settings becomes the aggregator of §7 and the
Develop-menu sniffers become `panel/tabs/develop.py`, `default_enabled=False`.
*Accept:* standalone chat reads and sends; a profile with chat disabled starts no
reader child and opens no store.

**Wave 7 — Cleanup.**
Delete the delegating shims from `Panel`. Replace `_sync_monitors`, `_panic`,
`_on_close` and the tab-title hook with the four loops of §9. Add the «Вкладки»
settings page. Decide the open question of §14. `panel/__main__.py` should land
under ~900 lines.
*Accept:* `grep -n "self\._t(" panel/__main__.py` returns only shell chrome; the
four loops exist; `tests/test_panel_leaks.py` is green.

---

## 12. Testing

The fakes already exist; they get promoted.

* **`tests/fake_runtime.py`** — one `FakeRuntime` replacing the hand-rolled `_App`
  stand-ins in `test_panel_tabs_extra.py`, `test_panel_rally_tab.py`,
  `test_panel_secret_tasks.py`, `test_panel_command_post.py`. Echoing `t()`, a
  recording `LogBus`, a `GameLink` that refuses to connect, a `ChildFactory` that
  records commands instead of spawning.
* **A shared contract test.** For every tab in the registry: it imports, builds on a
  bare Tk root with a cold runtime, survives `apply_config({})`, `on_show`,
  `on_hide`, `panic` and `shutdown` in that order, and leaves no armed `after`
  chain behind. One test function, parametrised over `TABS` — so a new tab is
  covered the day it is registered. Skips without a display, like the existing ones.
* **A profile-compatibility test.** A frozen pre-migration `config.json` fixture
  loads into the binder and yields the same effective values, per tab.
* **A locale-ownership test.** Per §8.
* `tests/*.py` here are self-running scripts under Windows Python (there is no
  pytest in this environment) — the new ones follow that shape.

---

## 13. How this sits with the actions-first rule

`CLAUDE.md` is binding: every ability is one `src/lastwar_bot/actions/*.md`
scenario, and the panel only plays it. Three consequences for this plan:

* **This refactor is not an ability.** No `actions/*.md`, no `docs/farming.md`
  entry, no progress-bar redraw. It changes who owns code, not what the bot can do.
* **Moving game logic between panel files does not pay the actions-first debt.**
  Waves 2, 3 and 5 carry Lua sequences and gates (rally send, auto-loot budget,
  ghost order, the timer runner) from `__main__.py` into a tab package. That is a
  relocation, and it must not be reported as the debt being paid.
* **But it is the natural moment to pay it.** When a wave lifts a block that
  assembles Lua or holds a gate, prefer turning it into a scenario in the same wave
  and leaving the tab calling `run_action`. Where that is not cheap, the rule that
  still applies without exception is the second half: **no new** direct game logic
  may be added under `panel/` by this refactor. A wave may move debt; it may not
  create it.

---

## 14. Open question for the operator

**Does the log stay inside a tab, or move out of the notebook?**

Since #1183 the Main tab is the game strip plus the log. Once every other subject
has moved out, "Main" is the shell — and the natural shape is a permanently visible
log pane under the notebook, with the game strip above it. That is arguably better
(the log is what every tab writes to; it is never the thing you want hidden), but it
is a visible UX change and not a refactor.

**Recommendation:** keep Main as a tab through waves 1–6 so nothing about the layout
moves while the plumbing does, and decide this once in wave 7, on its own, with the
window in front of you.

---

## 15. What this plan deliberately does not do

* **No third-party tab loading.** A `panel/tabs_local/` scan for user-written tabs
  is a one-evening addition on top of the registry; it is not in scope, and adding
  it early would mean designing a stability guarantee for `PanelRuntime` that the
  migration itself still needs to break.
* **No daemon-side game lock** (§9).
* **No locale file split** (§8).
* **No settings key renames** (§6 rule 3).
* **No behaviour changes inside a migration wave.** A wave that both moves a tab and
  changes what it does cannot be reviewed, and cannot be bisected when the auto-loot
  budget goes wrong a week later.
