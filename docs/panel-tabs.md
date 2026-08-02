# Adding a tab to the panel

**Every new tab is a plugin. There is no other kind.** The shell (`panel/__main__.py`)
is a window with a notebook, a log and a menu; it does not know what any tab does, and
nothing you add may make it know.

This is the how-to. The reasoning behind it is
[`docs/research/panel-tabs-refactor.md`](research/panel-tabs-refactor.md); read that
when you want to know *why*, and this when you want to write one.

---

## The short version

```
panel/tabs/mything.py          one file — or panel/tabs/mything/ when it grows parts
```

```python
from tkinter import ttk

from .base import PanelTab


class MyThingTab(PanelTab):
    ID = "mything"
    TITLE_KEY = "tab.mything"          # by convention `tab.<ID>`; the registry assumes it
    ORDER = 400
    LOCALE_NS = ("mything",)
    NEEDS = frozenset({"daemon"})

    def build(self) -> None:
        self.tr(ttk.Label(self.parent), "mything.hint").pack(anchor="w", padx=10, pady=10)


if __name__ == "__main__":
    from .base import run_tab
    raise SystemExit(run_tab(MyThingTab))
```

Then one line in `panel/tabs/__init__.py`:

```python
TabSpec("mything", "panel.tabs.mything", "MyThingTab", order=400),
```

and two locale keys (`tab.mything`, `mything.hint`) in **both** `panel/locales/en.json`
and `ru.json`. That is the whole registration: the shell builds it, «Настройки →
Вкладки» lists it, the profile can switch it off, and

```
C:\Python312\python.exe -m panel.tabs.mything --profile main
```

opens it in a window of its own.

---

## What a tab declares

All of these are class attributes with defaults, so declare only what is true.

| | What it is | When to set it |
|---|---|---|
| `ID` | The key in the profile and the name on the command line. | Always. |
| `TITLE_KEY` | Locale key of the tab's label. **Must equal the registry's** — the notebook labels a tab before building it, and the contract test pins the two together. | Always; keep it `tab.<ID>`. |
| `ORDER` | Where it sits. Existing tabs are spaced by tens, so there is room between any two. | Always. |
| `DEFAULT_ENABLED` | Is it in a fresh profile's list. `False` for something most people never use — `develop` is the example. | Rarely. |
| `PREFERRED_SIZE` | The standalone window's default geometry. | If `760x600` is wrong for it. |
| `LOCALE_NS` | The locale prefixes this tab owns. | Always — it is what keeps the two locale files reviewable. |
| `NEEDS` | `"daemon"` / `"children"` / `"actions"` / `"schedule"`. Shown beside the tab on the «Вкладки» page, so a person can see what switching it on costs. | Always. |
| `SETTINGS` | `{key: default}` the tab adds to the Settings knobs. | If it has knobs of its own. |
| `LEGACY_KEYS` | `{block key: old flat key}` — how the profile spelled this setting before the tab existed. | Only when moving existing settings; see below. |
| `SETTINGS_PAGE_KEY` | Locale key of the page this tab contributes to «Настройки». | If it has a settings page. Then implement `settings_page(parent)`. |
| `TIMERS` / `TRIGGERS` | Errands the tab brings with it (§3.2). | If it has any; see below. |
| `EAGER` | Load at boot instead of on first show. | Only if `ensure_loaded` brings up something that must be RUNNING. |

---

## `ensure_loaded` vs `on_show` — the one that bites

They are not the same and the difference costs a game round trip on every start.

* **`ensure_loaded()` — bring up what the tab is FOR.** A capture listening for an event
  that will not wait for a click; a watcher spending a daily budget. Called at boot for
  an `EAGER` tab and on first show otherwise, so **it must be idempotent**.
* **`on_show()` — somebody is looking.** A read that only draws. Called on every show,
  so a one-time seed gates itself on its own flag.

Putting a read in `ensure_loaded` on an `EAGER` tab makes every profile pay for it at
start-up, for a tab that may never be opened. The contract test asserts an `EAGER`
tab's `ensure_loaded` touches no game, and it is there because that exact thing
happened.

The rest of the lifecycle: `on_hide`, `on_profile_switch` (a different account — bounce
children, re-read files), `on_language_change` (only for what `tr` cannot re-render),
`panic` («Стоп всё» — stop what you hold and untick the boxes that say so), `shutdown`
(the window is closing — children, listeners, `rt.tick.disarm(...)`, bus
unsubscribes).

---

## The runtime is the only thing you get

`self.rt` is a `PanelRuntime` (`panel/runtime/host.py`). It is identical in the shell
and standalone, which is what makes a tab launchable at all.

| | |
|---|---|
| `rt.t(key, **fmt)` / `rt.tr(widget, key)` | words; `self.t` / `self.tr` are the same |
| `rt.say(tag, key)` / `rt.put(line)` | the log sink (no widget — «Главная» owns the view) |
| `rt.profiles` | the active profile's paths |
| `rt.settings` | knobs: `opt_int` / `opt_str` / `opt_bool` / `opt_float`, `vars[key]` (one Tk variable per knob, made by the runtime before any tab is built), and `changed()` |
| `rt.game` | `evaluator()`, `client`, `up()`, `claim()` / `release()`, `jump()`, `port()` |
| `rt.actions` | `run(name, args)`, `play(...) -> Outcome`, `run_text`, `resolve`, `problem` |
| `rt.play_async(name, args, …)` | run a scenario on a worker under the claim |
| `rt.children` | `spawn(...)` (a monitored child) / `spawn_raw(...)` (read it yourself) |
| `rt.tick` | `arm(name, ms, fn)` / `disarm(name)` — **named**, so a loop started twice is started once |
| `rt.bus` | `publish(topic, payload)` / `subscribe(topic, fn) -> unsubscribe` |
| `rt.tabs.get(id)` | another tab, **or `None`** — it may not be in this window |
| `rt.schedule` | the errands; built on first ask, started only by the shell |
| `rt.root` | for `after()` / `bell()` — **not** to build into; build into `self.parent` |

---

## Forbidden

1. **No game logic.** An ability is one `src/lastwar_bot/actions/*.md` scenario and the
   panel plays it — `CLAUDE.md` is binding on this. No assembling Lua, no walking a
   sequence of game steps, no holding an ability's gates (quota left, is-it-open-today,
   "collect first, then heal") in a tab. If the DSL lacks a primitive, add the
   primitive, document it in `docs/dsl.md`, then write the scenario.
2. **No `app`.** There is no app. If you catch yourself wanting `self.app._something`,
   the something belongs on the runtime or on your tab.
3. **No `import panel.__main__`, ever.** `python -m panel` executes that file *as*
   `__main__`, so importing it re-executes the whole panel as a second module. This is
   why the runtime exists. If you need something that lives there, move it into
   `panel/runtime/` first.
4. **No game in `build()`.** A standalone tab opens with no daemon, no client and no
   network. Everything live goes in `ensure_loaded` / `on_show`. The contract test
   builds every tab against a cold runtime and asserts nothing was asked of the game.
5. **No saving by yourself.** Return `config()`, accept `apply_config(raw)`, list
   `persist_vars()`; the container writes the profile. For a control that is not a Tk
   variable (a tri-state button, a combobox), call `rt.settings.changed()`.
6. **When you move a method here, bring its callers.** A method that leaves
   `panel/__main__.py` leaves a `self._whatever()` behind that still parses, still
   imports, and raises the first time that line runs. #1184 left three, and the one in
   `_apply_settings_to_ui` meant the panel did not open at all (#1191). What a tab has
   to re-draw after a restored value, the tab does at the end of its own
   `apply_config` — the shell must never name a widget it does not own. Run
   `C:\Python312\python.exe tests\test_panel_dangling_refs.py`: it fails on any
   `self.x` a class cannot possibly have, in the shell and in every tab.

---

## Settings, and moving existing ones

A tab's block lives at `tabs.config.<ID>` in the profile. `config()` returns it,
`apply_config()` restores it, `persist_vars()` lists the variables whose change means
"write now".

When you are **moving** settings that already exist as flat keys, `LEGACY_KEYS` maps
your block's key to the old flat one, and the binder reads either. Two rules:

* **Do not rename a key in the same change that moves it.** «Secret Tasks» spells all
  fourteen of its keys exactly as the flat profile did, so `LEGACY_KEYS` is an identity
  map. A lost setting and a migration bug look identical; keep them apart.
* The container **dual-writes** for one release — the new block and the old flat keys —
  so a profile touched by the new panel still opens in the old one.

---

## Errands a tab brings with it

If the thing your tab does should also happen on a clock or when a push lands, declare
it rather than wiring it:

```python
TRIGGERS = (TriggerSpec(name="mything_refresh", event="push.some.thing",
                        handler="refresh_live"),)
```

`handler` names a **method on your tab**. The schedule binds it when the tab is built —
which means a trigger whose tab is not in this profile is **not offered**: no listener
is spawned and nothing fires into a tab that is not there. Set `needs_game=True` if the
handler needs the client up; otherwise it runs before the daemon gate, which is right
for a repaint that degrades gracefully.

`scenario=` instead of `handler=` names an `actions/*.md` and stays data — that belongs
to the bot, not to your tab, and is always offered.

---

## Reaching another tab

Through the runtime, and tolerating absence:

```python
other = self.rt.tabs.get("secret_tasks")
if other is not None:
    other.refresh()
```

If it is a fact rather than a call, publish it: `rt.bus.publish("inventory.changed")`.
The bus is deliberately tiny — no wildcards, no ordering, no replay. `subscribe` returns
the unsubscribe callable, and `shutdown()` must call it.

---

## Before you call it done

```
C:\Python312\python.exe tests\test_panel_tab_contract.py
C:\Python312\python.exe tests\test_panel_dangling_refs.py
```

The second one is source-only and takes a second: no class in the panel may mention a
`self.x` it cannot have. The first covers your tab the moment it is in the registry: it must import, build cold, request no
game during `build()` (nor during `ensure_loaded` if `EAGER`), survive
`apply_config` → `on_show` → `on_hide` → `panic` → `shutdown`, and leave no armed `after`
chain and no bus subscription behind.

Then check the two things a test cannot:

* `python -m panel.tabs.<id> --profile <name>` opens and works;
* unticking it in «Настройки → Вкладки» and restarting leaves no trace of it — no
  widgets, no settings page, no listener, no capture.
