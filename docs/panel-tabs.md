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

and two locale keys (`tab.mything`, `mything.hint`) in **every** shipped locale —
**all eleven** files in `panel/locales/`, translated, in this same change
(see «Not a word of it is written in the tab» below). That is the whole registration:
the shell builds it, «Настройки →
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
| `LOCALE_NS` | The locale prefixes this tab owns. | Always — it is what keeps the locale files reviewable. |
| `NEEDS` | `"daemon"` / `"children"` / `"actions"` / `"schedule"`. Shown beside the tab on the «Вкладки» page, so a person can see what switching it on costs. | Always. |
| `SETTINGS` | `{key: default}` the tab adds to the Settings knobs. | If it has knobs of its own. |
| `LEGACY_KEYS` | `{block key: old flat key}` — how the profile spelled this setting before the tab existed. | Only when moving existing settings; see below. |
| `SETTINGS_PAGE_KEY` | Locale key of the page this tab contributes to «Настройки». | If it has a settings page. Then implement `settings_page(parent)`. |
| `AGGREGATES_TABS` | Does this tab draw parts contributed by OTHER tabs? Such a tab is built last, whatever its `ORDER` (below). | Only «Настройки» sets it. Set the matching `aggregates=True` on its registry entry too. |
| `TIMERS` / `TRIGGERS` | Errands the tab brings with it (§3.2). | If it has any; see below. |
| `EAGER` | Load at boot instead of on first show — and be DRAWN at boot with it. | Only if `ensure_loaded` brings up something that must be RUNNING. |
| `LAZY` | Is `build()` allowed to wait until somebody looks at the tab? **True by default**; see the section below for what it asks of you. | Never, unless your tab must exist before it is looked at — and then say why beside it. |
| `WEB_SCREEN` | Does this tab hand the phone a screen (`web_view` / `web_press`)? | Always — and `True` unless it is one of the three that must not (below). |

`DEFAULT_ENABLED` is what a profile that has NEVER opened «Настройки → Вкладки»
behaves by — the code's own constant. A profile that HAS opened that page keeps
its own tick list from then on (`tabs.enabled` in its `config.json`) — except that
"its own" is not "written by itself": every profile but the `default` one stores
only what it overrides, and reads back `tabs.enabled`/`tabs.known` from the
`default` profile's own `config.json` for everything it never touched itself
(`panel/profile.py`, `_deep_merge`/`_deep_diff`, #1246). So the one place that
controls which tabs are on for every profile at once is the `default` profile's
own Settings page — tick a tab there and every profile that never ticked it for
itself picks it up on its next start. A profile that DOES want to differ (its own
tick list) keeps overriding the default exactly as before.

---

## `build()` runs when somebody looks, not when the page is made

**A tab is DRAWN the first time it is shown** (`LAZY`, #1215). The page makes every tab
it has — the class is imported, `__init__` runs, the tab is registered, its errands are
adopted, its saved block is handed over — and then stops. Fourteen of the fifteen are a
frame with nothing in it until somebody clicks.

That is not a micro-optimisation: a page is built when the panel opens and again the
first time a profile is switched to, and drawing every tab cost between one and a half
and eight seconds of a window that answered nothing
([`panel-freezes.md`](research/panel-freezes.md) §3) — 1334 ms → 471 ms measured on a
real page, 16 tabs drawn → 4.

### What it asks of you

Four things reach a tab that nobody has opened. Write for them and the flag needs no
thought at all:

| what reaches it | what that means for you |
|---|---|
| **its saved block** | The container hands it over with `restore()` and asks for it back with `stored_config()`. An undrawn tab hands back exactly what it was given, so nothing is lost. Anything `config()` reads that is not a widget — a plan, a set, a catalogue — goes in `__init__`, and then it is right either way. |
| **a trigger it declared** | It fires on the wire whether or not anybody is looking. Keep the state in `__init__` and guard the repaint: `stats.track` tallies into a file and posts a redraw that returns early with no grid, `DataTab.refresh_live` does nothing until the tab has been opened once. |
| **the phone** | `web_view` / `web_press` go through the runtime, which DRAWS the tab before asking it. The phone must not see less than the window. |
| **the lifecycle** | `panic`, `resume`, `on_profile_switch`, `on_language_change` and `shutdown` are NOT called on an undrawn tab. It started nothing and holds nothing, and it reads what it needs when it is first shown. |

So the rule of thumb is the one the duel already followed: **`__init__` makes the state,
`build()` only draws it.** `VsDuelTab` makes every variable, default and key of its week
in `__init__` and lays the six day frames out in `build()`; the plan its scenarios read
answers the same before and after anybody opens the tab.

### Reaching a tab that may not be drawn

`rt.tabs.get(id)` **draws the tab before handing it over** when you are on the Tk thread,
so ordinary cross-tab code needs no change. Off the Tk thread it hands over whatever is
there — widgets are made nowhere but the event loop — so a background caller that needs
more than the tab's own state hands the work over with `rt.post` first. `rt.tabs.peek(id)`
is the one that never draws (the container and the tests use it), `rt.tabs.drawn` is the
tabs somebody has looked at, and `rt.tabs.realize(tab)` draws one on purpose.

`tests/test_panel_tab_contract.py` covers all of it for your tab the moment it is in the
registry: that it is lazy, that an unopened one keeps its settings, and that a trigger
firing into an undrawn one neither raises nor draws it.

---

## `ensure_loaded` vs `on_show` — the one that bites

They are not the same and the difference costs a game round trip on every start.

* **`ensure_loaded()` — bring up what the tab is FOR.** A capture listening for an event
  that will not wait for a click; a watcher spending a daily budget. Called at boot for
  an `EAGER` tab and on first show otherwise, so **it must be idempotent**. It always
  runs on a DRAWN tab: an `EAGER` one is built at boot for exactly this reason — what it
  starts usually asks its own checkbox whether it is switched on.
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
| `rt.settings` | knobs: `opt_int` / `opt_str` / `opt_bool` / `opt_float`, `vars[key]` (one Tk variable per knob, made by the runtime before any tab is built), and `changed()`. **Three of them are not knobs**: `launcher`, `game_exe` and `win_python` are `runtime.settings.MACHINE_KEYS` — one answer per machine, from `tools/lib/game_paths.py`, so a value in a profile's file is ignored and never written back (#1252). Read them the same way; do not offer a box for one. The daemon port is not typed either — `panel/runtime/provision.py` hands it out with the Windows session, one client per profile. |
| `rt.game` | `evaluator()`, `client`, `up()`, `claim()` / `release()`, `jump()`, `port()` |
| `rt.actions` | `run(name, args)`, `play(...) -> Outcome`, `run_text`, `resolve`, `problem` |
| `rt.play_async(name, args, …)` | run a scenario on a worker under the claim |
| `rt.children` | `spawn(...)` (a monitored child) / `spawn_raw(...)` (read it yourself). Both are **owned**: the runtime ends every child it started when the window closes, and a run that was killed rather than closed has its leftovers ended on the next start (#1212). Stop yours in `shutdown` anyway — that is what unticks the box and says so in the log; this is only the floor under it. |
| `rt.tick` | `arm(name, ms, fn)` / `disarm(name)` — **named**, so a loop started twice is started once |
| `rt.bus` | `publish(topic, payload)` / `subscribe(topic, fn) -> unsubscribe` |
| `rt.activity` | `with rt.activity.step("activity.x", **fmt):` — what the panel is doing right now, on the strip along the bottom of the window |
| `rt.tabs.get(id)` | another tab, **or `None`** — it may not be in this window |
| `rt.schedule` | the errands; built on first ask, started only by the shell |
| `rt.squads` | where every squad is and how much stamina is left: `at_base(n)` (`None` when it could not be read), `read(force=…)` off the Tk thread, `latest()` to draw with, `watch(fn) -> unwatch` — the poll runs only while somebody is watching. Built on first ask; the reading itself is `actions/read_squad_state.md`. |
| `rt.post(fn)` | run `fn` on the Tk thread from a background thread. `self.post` is the same. **The only way back from a worker** — see «Coming back from a background thread» below |
| `rt.root` | for `bell()`, and for `after(<delay>, …)` ON THE TK THREAD — **not** to build into (build into `self.parent`), and never for a hand-over (`rt.post`) |

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
7. **No words written in the tab.** `text="Обновить"` is a bug — every string a person
   reads is a locale key, in every shipped locale. The next section is the whole rule;
   `CLAUDE.md` is binding on it.
8. **No `rt.root.after(0, …)` from a background thread.** It looks like the free
   hand-over and it is the opposite of one: see the section below. Use `self.post`.

---

## What is NOT forbidden: a button that STARTS something

**«Состояние считается из игры, но выполнение можно вызывать.»** A tab that draws
readings may also offer to run the ability behind them, and that is ordinary rather than
a compromise. The line to hold is between the two verbs:

* **the state is READ.** Nothing a person does to the panel may change what a reading
  says. No box to tick, no «mark done», no counter the panel keeps for itself — the
  moment it kept one, the same errand done in the game, on a phone or by a second client
  would stop being counted, and the board would be confidently wrong instead of merely
  late;
* **the doing is OFFERED.** A press plays a scenario and then re-reads. Whatever the
  reading says next is what the row says next — including «still to do», when the game
  refused. A row that stays red after a press is information, not a bug.

They only look like the same rule. «Чеклист» lost its nine «Выполнить» to that confusion
(#1239 — «a button that starts something is a button somebody expects to have marked the
line»), and the board became something you could read but not use; #1257 put them back.
So when the temptation comes round again: **the objection is to MARKING, never to
pressing.** The way to keep them apart in code is to have exactly one path — the
checklist's `Errand.scenario` + `run(key)` — where a press plays the ability and calls
the refresh, and no path at all where anything writes a state.

Which lines get a button is a decision to be written down: nine of the checklist's
thirteen read errands have one. Two of the rest have no ability at all yet, and the
other two have an ability that has to PARK its targets with a tool before the recipe
can spend them (#1188), so a bare press of the recipe would succeed and rob nothing. That is in `.model`'s comments
beside the catalogue, and pinned by a test — because «no button here» has to be a reason
and not an oversight.

---

## One state, several places — a control may be drawn twice, never copied

A switch may appear in more than one place on a tab, and sometimes it should. What may
never appear twice is the STATE behind it.

**Why it comes up.** A control lives where it belongs to — the ★ sniffer's switch on the
★ page, the ghost sniffer's on the page its findings land on. That is correct and it is
not always findable. Live (#1264) the person reported both monitoring switches
«missing»: the ★ one had moved off the frame at the top of the tab, which still stood
there under its old title «Секретные задания» holding only the map sweep, and the ghost
one sat on a fifth page called «Призрак: карта» while the page anyone searches under is
called «Операция Призрак». Both boxes were built, mapped, and 400 px down a notebook
nobody had a reason to open. **A control in the right place that nobody finds is worse
than one in a slightly wrong place, because everything about it looks fine.**

**How to draw it twice.** Bind both widgets to the ONE variable the tab already has, and
give both the same `command`:

```python
# ✅ the frame at the top, and the page it belongs to — one variable, one toggle
self.tr(ttk.Checkbutton(bar, variable=self.monitor_var,
                        command=self.capture.toggle), "secret.monitoring.stars")
self.tr(ttk.Checkbutton(page, variable=self.monitor_var,
                        command=self.capture.toggle), "secret.monitoring.stars")
```

```python
# ❌ the version that rots: a second variable, kept in step by hand
self._monitor_top = tk.BooleanVar(value=self.monitor_var.get())   # agrees today
```

Tk moves every checkbutton bound to one variable, so the pair cannot disagree even in
the cases nobody wrote code for — a capture that stops on its own, a config restored on
start-up, a press arriving from the phone. A hand-synchronised copy agrees until the
first of those, and then one of the two is lying with no way to tell which.

Same on the phone: the SAME action `id` on both cards, built by one small method rather
than two literals, so the next edit to that button lands in both places
(`_ghost_monitor_action`). And say what it turns on rather than just «Мониторинг» — a
screen with two of them is scrolled past its own card titles.

**A duplicate is a decision, not clutter.** Write beside it why the second one is there
and that it shares the variable; `tests/test_panel_secret_tasks_switches.py` counts the
boxes and asserts they name one variable, so removing a copy as «tidying» fails rather
than quietly returning the tab to the state that was reported as broken.

**This is not the mirror rule.** Window ↔ web is about the same control existing on
BOTH front-ends. This is about the same control appearing more than once on ONE of them
— and both rules end in the same place: one state, however many places show it.

---

## Coming back from a background thread

A tab reads the game off the Tk thread and then has to paint what it found. **That
hand-over is `self.post(fn)`, always.**

```python
def refresh(self) -> None:
    threading.Thread(target=self._work, daemon=True).start()

def _work(self) -> None:
    data = self.fetch()                 # the game, on a worker
    self.post(lambda: self.render(data))   # ✅ back to the Tk thread
    # self.rt.root.after(0, lambda: self.render(data))   ❌ never
```

`after(0, …)` from a thread that is not Tk's does not schedule anything. tkinter
registers a Tcl command for the callback and then makes the `after` call, and from a
foreign thread `_tkinter` runs neither: it queues each as an event for the Tk thread and
**blocks the caller** until the event loop gets round to it. Measured with four profiles
open, that is **8.6 ms on average and 17 ms at the tail, per hand-over** — so a tab of
one profile reporting a reading sits on the thread that draws all the others, and every
other profile's work sits behind it (`tools/dev/panel_thread_bench.py`,
docs/research/multi-profile-panel.md §12). `post` costs 17 µs and touches no Tk at all.

It is also the difference between working and not during the BOOT. While the window is
pumping `update()` by hand — which is most of a panel's start-up — the same call raises
«main thread is not in main loop», and that killed the thread that made it: a monitor
that ended during those seconds left its checkbox ticked for a process that had gone.

The same applies to `rt.settings.opt_*`: read them from wherever you like. They answer
from a thread-safe mirror off the Tk thread and only touch the variable when the caller
IS the Tk thread, so a background read costs a dict lookup rather than a round trip
through the window.

`tests/test_panel_parallel_profiles.py` parses everything under `panel/` and fails on the
next `after(0, …)` written.

---

## Settings, and moving existing ones

A tab's block lives at `tabs.config.<ID>` in the profile. `config()` returns it,
`apply_config()` restores it, `persist_vars()` lists the variables whose change means
"write now". Those three are yours; the container talks to them through `restore()` and
`stored_config()`, which is what makes an unopened tab safe to save (above) — you
implement the first three and never call the last two.

When you are **moving** settings that already exist as flat keys, `LEGACY_KEYS` maps
your block's key to the old flat one, and the binder reads either. Two rules:

* **Do not rename a key in the same change that moves it.** «Secret Tasks» spells all
  fourteen of its keys exactly as the flat profile did, so `LEGACY_KEYS` is an identity
  map. A lost setting and a migration bug look identical; keep them apart.
* The container **dual-writes** for one release — the new block and the old flat keys —
  so a profile touched by the new panel still opens in the old one.

### The page a tab contributes, and why the order matters

`SETTINGS_PAGE_KEY` + `settings_page(parent)` puts a page of your own inside
«Настройки». It travels with the tab: switch the tab off in the profile and its page is
gone too, which is the whole point of the aggregator (§6 of the refactor notes).

**The order tabs are built in is not the order they sit in.** «Настройки» walks
`rt.tabs.live` and asks each tab for its page, so it can only draw the tabs that already
exist — and it sits at `ORDER` 40 while most contributors are in the hundreds. That is
what `AGGREGATES_TABS` is for: a tab that declares it is built LAST
(`panel.tabs.build_order`), keeping its place on the strip.

It is worth knowing because of how it fails. A contributor built after the aggregator
raises nothing and logs nothing — its page is simply not there. «Автосбор» vanished that
way and stayed vanished, and with it the squad list the rally auto-join spends, so the
auto-join read an empty list and refused every time (#1237). If you add a second
aggregator one day, set the flag in both places and let
`tests/test_panel_tab_contract.py` pin the order.

**No tab uses this today**, and that is worth saying rather than leaving to be
discovered. «Автосбор» was the only contributor and it moved onto the «Ралли» tab in
the same task: nothing on it was a knob of the PANEL — not a path, not a port, not an
interpreter — it was all about rallies, and it belongs beside the switches that spend
it. Before you reach for `SETTINGS_PAGE_KEY`, ask whether your page is really a panel
setting or just a setting your tab happens to own. If it is the second, put it on the
tab; «Настройки» is for the things that are true of the installation rather than of the
game.

---

## Listening on the wire — subscribe, never spawn

A tab (or anything else) that wants to hear a game push asks the runtime's one ear:

```python
self._off = self.rt.wire.subscribe("push.alliance.march", self._on_march)
...
self._off()          # in shutdown / on_hide — the ear closes with the last subscriber
```

**Never spawn `wire_event_monitor.py` yourself.** One capture per profile carries the
union of every subscribed pattern and dispatches by substring in Python
(`panel/runtime/wire.py`). A process per listener is what this replaced: each opened its
own npcap handle on the same interface and decoded every packet the game sent to read
one command name out of it, and with a runtime per open profile the bill was
*listeners × profiles* — every term the same work done again.

Three things to know before you subscribe:

* **the callback runs on the child's reader thread**, not on Tk. Hand work to a queue;
  anything that draws goes through `self.post`;
* **it is called with `None` when the ear closes.** That is «the capture died», not a
  command — treat it the way the trigger watcher does, by forgetting the subscription
  and re-subscribing on the next sync;
* **an empty pattern is refused**, because `"" in command` matches everything and a
  typo would quietly subscribe you to the whole of the game's traffic.

A capture that decodes payloads rather than matching command names — the rally monitor's
army archive, the leaderboard collector — is still a child of its own; the hub carries
command NAMES, and folding those in would mean moving their decoding into it.

**A capture you spawn yourself must still be told whose client it is.** Two accounts of
the same game dial the same server port, so the packet filter cannot separate them and a
capture hears both — one profile's auto-join spending squads because the other's alliance
raised a banner. Pass the profile's pids and the capture keeps only those sockets:

```python
for pid in game_process.profile_pids(self.rt.settings):
    cmd += ["--client-pid", str(pid)]
```

An empty answer means «could not tell», and then the capture stays machine-wide on
purpose: losing the separation is a fair price for an unanswerable question, while a
capture that went deaf would make a profile farming nothing look like one with nothing
to do.

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

## Not a word of it is written in the tab

Everything a person can read comes out of `panel/locales/`. Not «most of it», not
«everything except the little ones» — the label, the button, the checkbox, the hint, the
column head, the window title, the message box, the line in the log:

```python
# ❌ the tab speaks for itself
ttk.Button(self.parent, text="Обновить", command=self.refresh).pack()
ttk.Label(self.parent, text="Ничего не прочитано").pack()
messagebox.showerror("Ошибка", f"не удалось: {exc}")
self.rt.put("[mything] обновлено")

# ✅ the tab names a key and the runtime says it
self.tr(ttk.Button(self.parent, command=self.refresh), "mything.refresh").pack()
self.tr(ttk.Label(self.parent), "mything.empty").pack()
messagebox.showerror(self.t("mything.error.title"), self.t("mything.error", error=exc))
self.say("mything", "mything.refreshed")
```

`self.tr(widget, key)` registers the widget, so it re-labels itself when the language
changes; `self.t(key, **fmt)` is for a string you build yourself (a dialog, a treeview
cell, a status line) and has to be re-asked in `on_language_change`. Placeholders are
`{named}` and go through `str.format` — never glue a translated fragment onto another
one, because the order of the pieces is not the same in every language.

**And a key is added to every shipped locale in the same change, translated.** Three
files today: `en.json` (the canonical one), then `ru` `de` `fr` `es` `it` `pt` `pl` `tr`
`id` `vi`. Not English first and the others «when there is time» — a missing key falls
back to English *silently*, so half a tab in the wrong language looks exactly like a tab
that is finished, and nobody finds out for months. Add the key to all eleven or the tab
is not done.

You do not translate the game's own words. Anything the game has already named — a
rally, the Doom Elite, Ghost Ops, a Secretary — is copied out of the client's own
tables: the list is [`game-glossary.md`](game-glossary.md), and
`tools/game_locale.py --term "..."` answers for anything not on it.

The only literals allowed are the ones nobody reads as words — a numeric format
(`"(%d–%d)"`), a separator, a Tk option value, an internal tag such as the `label=`
handed to `run_text`. **If it can be translated, it is a key.**

`tests/test_panel_i18n.py` enforces both halves and takes a second:

```
C:\Python312\python.exe tests\test_panel_i18n.py
```

It fails on a key any shipped locale is missing (in either direction — a key nobody
uses any more has to go from all of them at once), and on a translatable literal handed
to a widget, a menu entry or a dialog anywhere under `panel/`.

The fourth is the phone's copy: that the three exempt tabs still have no screen, that
every word a screen names is a locale key that exists, that a screen is made of nothing
the renderer cannot draw, and that a button offered on a screen has a `web_press` that
answers for it. What it CANNOT check is «one side was edited and the other was not», in
either direction — that is a property of a diff, not of a snapshot, and it rests on the
rule and on review.

---

## A language is a file

There is no list of languages anywhere in the code, and none may be added. The Language
menu IS `panel/locales/`: the code comes from the file name, the label from the
`language.name` key **inside** that file, written in its own script.

So a person who wants the panel in their own language copies `en.json` to `fr.json`,
translates the values, sets `"language.name": "Français"` — and it is in the menu on the
next start. Nothing else is touched. (That is how the other ten got here: each is a file
and nothing else. What changed by shipping them is only the size of the chore — a new
key now has eleven translations to write instead of two.) (The label lives in the file rather than being
derived from the code because only the file can say it in its own script: a table of
`de → Deutsch` somewhere would be the same hard-coded list under another name, and a
bare `de` in the menu is not a language anyone recognises. `language.name` is spelled
like every other key so it is translated, reviewed and diffed with the rest.)

Ask through the runtime, never past it:

```python
self.rt.i18n.available()      # ['en', 'de', 'es', 'fr', …] — codes, default first
self.rt.i18n.name("ru")       # 'Русский' — what ru.json calls itself
self.rt.i18n.known("fr")      # is there a locale for it?
```

What it does when things are missing, because the panel now reads whatever is in that
directory and has to survive it:

| | |
|---|---|
| no `language.name` in the file | it still appears, labelled with its bare code |
| a key the file does not translate | falls back to English — a half-finished locale is usable |
| the file is not valid JSON | an empty locale, everything falls back; not a crash |
| the profile names a language with no file | English **and a line in the log** naming it; the remembered choice is not rewritten, so the language returns by itself when the file does |

What this means for a tab author is only what it always meant: put your keys in **every**
shipped file. `tests/test_panel_i18n.py` pins the rest, including that the table of
languages has not come back.

---

## The phone's copy of this tab, and keeping it in step

The panel has two front-ends: this window and the web one a phone opens
(`panel/web/`, docs/research/panel-web.md). A tab hands the second one its screen as
DATA and the browser draws it with a single renderer:

```python
WEB_SCREEN = True                       # this tab has a phone screen

def web_view(self) -> dict:
    """What the tab HAS — never a read of the game (see below)."""
    return {"cards": [{"title": "tab.hospital",
                       "rows":  [{"label": "hospital.wounded", "value": "128"}],
                       "items": [{"text": "Иванов", "detail": "30 · 12 480 000",
                                  "facts": [{"label": "rally_tab.soldiers",
                                             "value": "4200"}],
                                  "until": 1785776747.0,
                                  "pill": "squads.kind.home",
                                  "actions": [{"id": "join", "label": "rally.join"}]}],
                       "empty": "tabx.no_game"}],
            "now": time.time(),
            "actions": [{"id": "refresh", "label": "tabx.refresh"}]}

def web_press(self, action: str, args: dict) -> dict:
    return {"ok": True} if action == "refresh" else {"error": "unknown"}
```

**A press can belong to a card or to an item, not only to the screen.** `actions` at the
top level is the screen's own row of buttons; the same list ON A CARD is drawn as that
card's footer, and on an ITEM beside that row. Pick by what the press belongs to:
«События» puts «Атаковать сейчас» on the event's card (#1257), «Чеклист» puts one on each
errand row that is a scenario. All three reach the same `web_press`, so an id has to be
answered wherever it was offered — and an item's action carries `args`, which is how a
row says WHICH errand it is.

**Which fields are words and which are data is fixed.** `title`, `label`, `empty`,
`pill` are **locale keys** and are said by the browser out of the panel's own table;
`text`, `value`, `detail`, `note`, `head` and a fact's `value` are **data** — a player's
name, a count, a date. That is what puts a screen in eleven languages by construction:
the i18n test only reads `t()` calls in `.py`, so a sentence written into a dict would
sail past it. `tests/test_panel_web_screens.py` reads the views instead and fails on a
label that is not a key.

`until` is an epoch and `now` is the PANEL's clock: the phone counts down against the
panel's time rather than its own, because a tablet an hour out would otherwise call
every deadline expired.

**`web_view` must be CHEAP.** It runs on the Tk thread every time a phone opens the
screen, so it returns what the tab already holds. Reading the game belongs in the tab's
own refresh, which the phone asks for by pressing «Обновить» — a phone in a pocket must
not poll the client all day. The six `DataTab` tabs get this for free: the base class
caches the last reading and only the mapping (`web_cards`) is each tab's own.

### It travels in the same commit, in BOTH directions — this is binding

`CLAUDE.md`, «An edit travels between the window and the web, in BOTH directions, at
once». Two front-ends that drift are worse than one, because whoever is reading the
stale one has no way to know that is what they are reading.

| you changed | you also change, in the same commit |
|---|---|
| `build()` — a button, a field, a reading, a status line | `web_view()`, and `web_press()` if it is a press |
| `web_view()` — a card, a row, a fact, an action | `build()`, so the window has it too |

The second row is the one people forget. A control that exists only on the phone is a
control the person at the machine cannot find, and the next agent reading the tab has
no idea it is there — the drift is simply pointing the other way.

Three things bound it:

* **A press travels only when the ability is a scenario.** `web_press` runs
  `rt.actions` / `rt.play_async` and nothing else. Where a tab still drives the game by
  hand — or half by hand (#1188 — the secret-task and ghost robberies press through a
  scenario, but still spawn a tool to park the targets, because the recipe cannot fill
  the queue it spends), the web gets the reading and no button. First the whole ability
  through `rt.actions`, then the button.
* **A DIVERGENCE IS NOT YOURS TO DECIDE.** When the two sides genuinely should differ —
  something impossible on a phone, something pointless in a window — that is a
  conversation with the person, not a judgement call. Ask, agree, then write the
  exception with its reasoning into `CLAUDE.md` and into this file. Until it is written
  down it does not exist, and the rule stands. What is forbidden is the silent version:
  shipping one side, deciding alone that the other does not need it, leaving no trace —
  after which nobody can tell an exception from an omission.
* **Three tabs have no screen, and they are what a legal exception looks like:**
  `settings`, `web`, `develop` were proposed, argued and agreed, and the reasons are
  written in `CLAUDE.md`. `tests/test_panel_web_screens.py` fails if one of them grows
  a screen quietly — and a fourth exception is added the same way: ask, agree, write it
  in both files, pin it in the test.

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

## Saying what you are doing

Anything of yours that takes more than about a quarter of a second — a read of the game,
a child being started, a list being rebuilt — says so while it runs:

```python
with self.rt.activity.step("mything.reading", n=len(rows)):
    rows = self.fetch()
```

The shell paints the newest live step of every open profile on the strip along the
bottom of its window; a tab launched on its own has nobody listening and pays a
dictionary insert. **A step is a locale key and its arguments, never a sentence** — the
words are said by whoever draws them, in whatever language that window is showing, which
is also what lets a worker thread report without knowing the language at all. Several
steps may be live at once and the newest wins; when it ends, whatever is still running
underneath comes back into view.

Use it for work, not for state: it is «reading the roster», never «12 members». What a
tab has FOUND belongs on the tab, and what has HAPPENED belongs in the log.

---

## Before you call it done

```
C:\Python312\python.exe tests\test_panel_tab_contract.py
C:\Python312\python.exe tests\test_panel_dangling_refs.py
C:\Python312\python.exe tests\test_panel_i18n.py
C:\Python312\python.exe tests\test_panel_web_screens.py
```

The second one is source-only and takes a second: no class in the panel may mention a
`self.x` it cannot have. The first covers your tab the moment it is in the registry: it must import, build cold, request no
game during `build()` (nor during `ensure_loaded` if `EAGER`), survive
`apply_config` → `on_show` → `on_hide` → `panic` → `shutdown`, and leave no armed `after`
chain and no bus subscription behind. The third is the words: no literal a person can
read anywhere under `panel/`, and every key in every shipped locale.

Then check the two things a test cannot:

* `python -m panel.tabs.<id> --profile <name>` opens and works;
* unticking it in «Настройки → Вкладки» and restarting leaves no trace of it — no
  widgets, no settings page, no listener, no capture.
